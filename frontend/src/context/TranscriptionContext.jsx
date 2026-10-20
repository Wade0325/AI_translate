import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { message } from 'antd';
import { useModelManager } from '../components/ModelManager';
import { useTranscriptionSocket } from '../hooks/useTranscriptionSocket';
import { useUploadQueue } from '../hooks/useUploadQueue';
import { useDownloadBundle } from '../hooks/useDownloadBundle';
import { PROVIDER_LIST_FAILED, useProviderList } from '../hooks/useProviderList';
import {
  disabledReasonsFor,
  findModelCapabilities,
  modelForProvider,
  modelSupports,
  providerLabel,
  requiresApiKey,
} from '../utils/providerList';
import { api } from '../services/api';

const TranscriptionContext = createContext(null);

export const useTranscription = () => {
  const ctx = useContext(TranscriptionContext);
  if (!ctx) {
    throw new Error('useTranscription must be used within TranscriptionProvider');
  }
  return ctx;
};

export const TranscriptionProvider = ({ children }) => {
  const [fileList, setFileList] = useState([]);
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [isProcessing, setIsProcessing] = useState(false);
  // 'standard' | 'flex' | 'batch'
  const [processingMode, setProcessingMode] = useState('batch');
  const [multiSpeaker, setMultiSpeaker] = useState(false);

  const useBatchMode = processingMode === 'batch';

  const { getProviderConfig } = useModelManager();

  // 先選供應商、再選它的模型；兩者都照供應商清單的值送出，後端會驗證模型屬於這個供應商。
  // 還沒選時用預設：清單上的第一個供應商；換供應商時模型回到它的預設模型（第一個）
  const { providerList, failed: providerListFailed } = useProviderList();
  const [selection, setSelection] = useState({ provider: null, model: null });
  const provider = selection.provider ?? providerList?.[0]?.provider ?? null;
  const model = modelForProvider(providerList, provider, selection.model);

  const selectProvider = useCallback((nextProvider) => {
    setSelection({ provider: nextProvider, model: null });
  }, []);
  const setModel = useCallback((nextModel) => {
    setSelection((current) => ({ ...current, model: nextModel }));
  }, []);

  // 所選模型支援哪些輸入與處理方式；模型能力還沒載入時不限制，由後端把關
  const capabilities = findModelCapabilities(providerList, provider, model);
  const supports = useMemo(() => modelSupports(capabilities), [capabilities]);
  const reasons = useMemo(() => disabledReasonsFor(supports), [supports]);

  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [previewContent, setPreviewContent] = useState('');
  const [previewTitle, setPreviewTitle] = useState('');

  const socketManager = useTranscriptionSocket();
  const { downloadFile, downloadAllFiles } = useDownloadBundle(fileList);
  const { startRegular, startBatch } = useUploadQueue({
    fileList,
    setFileList,
    socketManager,
    onBatchSubmitted: () => {
      // 批次送出後解除 UI 處理鎖
      setIsProcessing(false);
      hasStartedProcessing.current = false;
    },
  });

  // 批次任務狀態輪詢：偵測 batch_pending 檔案是否已完成
  const hasBatchPending = fileList.some((f) => f.status === 'batch_pending');
  useEffect(() => {
    if (!hasBatchPending) return;
    const poll = async () => {
      try {
        const tasks = await api.batch.tasks();
        const bySession = new Map(tasks.map((t) => [t.session_id, t]));
        setFileList((current) => {
          const next = current.map((f) => {
            if (f.status !== 'batch_pending' || !f.sessionId) return f;
            const task = bySession.get(f.sessionId);
            if (!task || task.status === 'RETRIEVED') {
              return { ...f, status: 'completed', statusText: '批次結果已儲存，可在 History 頁面下載' };
            }
            if (task.status === 'COMPLETED') {
              return { ...f, statusText: '批次完成，請前往 Tasks 頁面取回結果' };
            }
            return f;
          });
          const changed = next.some((f, i) => f !== current[i]);
          return changed ? next : current;
        });
      } catch {
        // 輪詢失敗時靜默忽略
      }
    };
    poll();
    const id = setInterval(poll, 30000);
    return () => clearInterval(id);
  }, [hasBatchPending]);

  // 所有 processing 檔案結束後自動解除 isProcessing 並總結結果
  const hasStartedProcessing = useRef(false);
  useEffect(() => {
    const stillProcessing = fileList.some((f) => f.status === 'processing');
    if (stillProcessing) {
      hasStartedProcessing.current = true;
    }
    if (isProcessing && hasStartedProcessing.current && !stillProcessing) {
      setIsProcessing(false);
      hasStartedProcessing.current = false;

      const completed = fileList.filter((f) => f.status === 'completed').length;
      const failed = fileList.filter((f) => f.status === 'error').length;
      const cancelled = fileList.filter((f) => f.status === 'cancelled').length;

      if (failed > 0 && completed === 0) {
        message.error(`${failed} 個任務失敗`);
      } else if (failed > 0) {
        message.warning(`完成 ${completed} 個，${failed} 個失敗`);
      } else if (completed === 0 && cancelled > 0) {
        message.info(`${cancelled} 個任務已取消`);
      } else {
        message.success(`${completed} 個任務已完成`);
      }
    }
  }, [fileList, isProcessing]);

  const handleOpenPreview = useCallback((record) => {
    setPreviewTitle(`預覽內容: ${record.name}`);
    setPreviewContent(record.result?.txt || '沒有可預覽的文字內容。');
    setIsPreviewModalVisible(true);
  }, []);

  const handleClosePreview = useCallback(() => {
    setIsPreviewModalVisible(false);
    setPreviewContent('');
    setPreviewTitle('');
  }, []);

  const handleReprocess = useCallback((uidToReprocess) => {
    const target = fileList.find((f) => f.uid === uidToReprocess);
    if (target) {
      message.info(`任務 "${target.name}" 已重新加入佇列。`);
    }
    setFileList((current) =>
      current.map((file) =>
        file.uid === uidToReprocess
          ? {
              ...file,
              status: 'waiting',
              percent: 0,
              tokens_used: 0,
              cost: 0,
              result: null,
              statusText: '等待處理',
              task_uuid: null,
              error: null,
            }
          : file
      )
    );
  }, [fileList]);

  const clearAllFiles = useCallback(() => {
    socketManager.closeAll(1000);
    setFileList([]);
    message.success('已清除所有任務');
  }, [socketManager]);

  // 取消單檔轉錄：後端設置取消旗標並 revoke，最終狀態由 WS 的 CANCELLED 訊息更新
  const cancelTranscription = useCallback(async (uid) => {
    const target = fileList.find((f) => f.uid === uid);
    if (!target || target.status !== 'processing') return;

    setFileList((current) =>
      current.map((f) => (f.uid === uid ? { ...f, statusText: '正在取消...' } : f))
    );
    try {
      const res = await api.transcription.cancel(uid);
      if (res?.cancelled === false) {
        message.warning('任務尚未提交到佇列（可能還在上傳），請稍後再試。');
        setFileList((current) =>
          current.map((f) =>
            f.uid === uid && f.status === 'processing'
              ? { ...f, statusText: '處理中...' }
              : f
          )
        );
        return;
      }
      message.info(`已取消任務：${target.name}`);
    } catch (err) {
      message.error(`取消失敗: ${err.message}`);
      setFileList((current) =>
        current.map((f) =>
          f.uid === uid && f.status === 'processing'
            ? { ...f, statusText: '處理中...' }
            : f
        )
      );
    }
  }, [fileList]);

  // globalPrompt：轉錄頁的全域提示詞，送給沒有每檔設定提示詞的檔案（不必先按 Apply to All）
  const handleStartTranscription = useCallback(async ({ globalPrompt = '' } = {}) => {
    if (!provider || !model) {
      message.error(providerListFailed ? PROVIDER_LIST_FAILED : '供應商清單還在載入，請稍後再試');
      return;
    }

    const config = await getProviderConfig(provider);
    // 設定裡只有遮罩後的金鑰：這裡只確認已設定，實際金鑰由後端從資料庫取用、不隨任務送出
    const hasApiKey = Boolean(config?.apiKeys?.[0]);
    if (requiresApiKey(providerList, provider) && !hasApiKey) {
      message.error(`請先在設定頁為 ${providerLabel(providerList, provider)} 設定 API 金鑰。`);
      return;
    }
    if (useBatchMode && reasons.batch) {
      message.error(reasons.batch);
      return;
    }

    const defaults = {
      sourceLang: targetLang,
      multiSpeaker,
      serviceTier: processingMode === 'flex' ? 'flex' : null,
      prompt: globalPrompt,
    };

    setIsProcessing(true);

    const runner = useBatchMode ? startBatch : startRegular;
    const result = await runner({ provider, model, promptTemplate: config?.prompt, defaults, supports });

    if (result?.skipped) {
      setIsProcessing(false);
      message.warning('沒有等待處理的新檔案！');
    }
  }, [
    provider,
    model,
    providerList,
    providerListFailed,
    getProviderConfig,
    targetLang,
    multiSpeaker,
    processingMode,
    useBatchMode,
    supports,
    reasons,
    startBatch,
    startRegular,
  ]);

  const value = {
    fileList,
    setFileList,
    targetLang,
    setTargetLang,
    providerList,
    providerListFailed,
    provider,
    selectProvider,
    model,
    setModel,
    disabledReasons: reasons,
    isProcessing,
    processingMode,
    setProcessingMode,
    multiSpeaker,
    setMultiSpeaker,
    handleStartTranscription,
    downloadFile,
    downloadAllFiles,
    clearAllFiles,
    handleReprocess,
    cancelTranscription,
    isPreviewModalVisible,
    previewContent,
    previewTitle,
    handleOpenPreview,
    handleClosePreview,
  };

  return (
    <TranscriptionContext.Provider value={value}>
      {children}
    </TranscriptionContext.Provider>
  );
};
