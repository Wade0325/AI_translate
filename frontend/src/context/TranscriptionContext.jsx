// @ts-nocheck
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { message } from 'antd';
import { useModelManager } from '../components/ModelManager';
import { useTranscriptionSocket } from '../hooks/useTranscriptionSocket';
import { useUploadQueue } from '../hooks/useUploadQueue';
import { useDownloadBundle } from '../hooks/useDownloadBundle';
import { PROVIDER_LIST_FAILED, useProviderList } from '../hooks/useProviderList';
import {
  allowedProcessingMode,
  disabledReasonsFor,
  findModelCapabilities,
  missingApiKey,
  modelSupports,
  providerLabel,
  resolveSelection,
  withModel,
  withProvider,
} from '../utils/providerList';
import { loadLastSelection, saveLastSelection } from '../utils/lastSelection';
import { forRetranscription, requestDefaults } from '../utils/transcribeRequest';
import { cancelFile } from '../utils/cancelOutcome';
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
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [isProcessing, setIsProcessing] = useState(false);
  // 使用者選的處理模式：'standard' | 'flex' | 'batch'。實際用的是下面的 processingMode
  const [chosenProcessingMode, setChosenProcessingMode] = useState('batch');
  const [multiSpeaker, setMultiSpeaker] = useState(false);
  // 轉錄頁的全域提示詞：補充說明，送給沒有每檔設定提示詞的檔案（不必先按 Apply to All），
  // 後端接在提示詞範本後面
  const [globalPrompt, setGlobalPrompt] = useState('');

  const { getProviderConfig } = useModelManager();

  // 先選供應商、再選它的模型；兩者都照供應商清單的值送出，後端會驗證模型屬於這個供應商。
  // 選擇的規則（預設、換供應商）見 utils/providerList.js 的 resolveSelection。
  // 開頁時沿用上次的選擇，換了就記下來（utils/lastSelection.js）
  const {
    providerList,
    failed: providerListFailed,
    reload: reloadProviderList,
  } = useProviderList();
  const [selection, setSelection] = useState(loadLastSelection);
  const { provider, model } = resolveSelection(providerList, selection);
  useEffect(() => {
    saveLastSelection(selection);
  }, [selection]);

  const selectProvider = useCallback((nextProvider) => {
    setSelection((current) => withProvider(current, nextProvider));
  }, []);
  const setModel = useCallback((nextModel) => {
    setSelection((current) => withModel(current, nextModel));
  }, []);

  // 所選模型支援哪些輸入與處理方式；模型能力還沒載入時不限制，由後端把關
  const capabilities = findModelCapabilities(providerList, provider, model);
  const supports = useMemo(() => modelSupports(capabilities), [capabilities]);
  const reasons = useMemo(() => disabledReasonsFor(supports), [supports]);

  // 換到不支援所選處理模式的模型時退回標準，之後換回來也維持標準（#162）
  const processingMode = allowedProcessingMode(chosenProcessingMode, supports);
  if (processingMode !== chosenProcessingMode) setChosenProcessingMode(processingMode);
  const useBatchMode = processingMode === 'batch';

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

  // 批次狀態輪詢：偵測 batch_pending 檔案是否已完成
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
      message.info(`"${target.name}" 已放回清單，按 Start 會另開新任務。`);
    }
    setFileList((current) =>
      current.map((file) => (file.uid === uidToReprocess ? forRetranscription(file) : file))
    );
  }, [fileList]);

  const clearAllFiles = useCallback(() => {
    socketManager.closeAll(1000);
    setFileList([]);
    message.success('已清除所有任務');
  }, [socketManager]);

  // 取消單檔轉錄：後端設置取消旗標並 revoke，最終狀態由 WS 的 CANCELLED 訊息更新；
  // 沒有取消時顯示的提示與檔案卡怎麼改見 utils/cancelOutcome.js
  const cancelTranscription = useCallback(async (uid) => {
    const target = fileList.find((f) => f.uid === uid);
    if (!target || target.status !== 'processing') return;

    setFileList((current) =>
      current.map((f) => (f.uid === uid ? { ...f, statusText: '正在取消...' } : f))
    );
    try {
      const { notice, apply } = await cancelFile(target, api);
      message.open(notice);
      if (apply) {
        setFileList((current) =>
          current.map((f) => (f.uid === uid && f.status === 'processing' ? apply(f) : f))
        );
      }
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

  const handleStartTranscription = useCallback(async () => {
    if (!provider || !model) {
      message.error(providerListFailed ? PROVIDER_LIST_FAILED : '供應商清單還在載入，請稍後再試');
      return;
    }

    const config = await getProviderConfig(provider);
    if (missingApiKey(providerList, provider, config)) {
      message.error(`請先在設定頁為 ${providerLabel(providerList, provider)} 設定 API 金鑰。`);
      return;
    }

    const defaults = requestDefaults({ language: sourceLang, multiSpeaker, processingMode, globalPrompt });

    setIsProcessing(true);

    // 提示詞範本不經前端：後端派送時從設定讀，接上每個檔案的補充說明（utils/transcribeRequest.js）
    const runner = useBatchMode ? startBatch : startRegular;
    const result = await runner({ provider, model, defaults, supports });

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
    sourceLang,
    multiSpeaker,
    globalPrompt,
    processingMode,
    useBatchMode,
    supports,
    startBatch,
    startRegular,
  ]);

  const value = {
    fileList,
    setFileList,
    sourceLang,
    setSourceLang,
    providerList,
    providerListFailed,
    reloadProviderList,
    provider,
    selectProvider,
    model,
    setModel,
    supports,
    disabledReasons: reasons,
    isProcessing,
    processingMode,
    setProcessingMode: setChosenProcessingMode,
    multiSpeaker,
    setMultiSpeaker,
    globalPrompt,
    setGlobalPrompt,
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
