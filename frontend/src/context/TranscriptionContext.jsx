import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { modelOptions, findProviderForModel } from '../constants/modelConfig';
import { useModelManager } from '../components/ModelManager';
import { useTranscriptionSocket } from '../hooks/useTranscriptionSocket';
import { useUploadQueue } from '../hooks/useUploadQueue';
import { useDownloadBundle } from '../hooks/useDownloadBundle';
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
  const [targetTranslateLang, setTargetTranslateLang] = useState(null);
  const [model, setModel] = useState(modelOptions.Google[0].value);
  const [isProcessing, setIsProcessing] = useState(false);
  // 'standard' | 'flex' | 'batch'
  const [processingMode, setProcessingMode] = useState('batch');
  const [multiSpeaker, setMultiSpeaker] = useState(false);

  const useBatchMode = processingMode === 'batch';

  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [previewContent, setPreviewContent] = useState('');
  const [previewTitle, setPreviewTitle] = useState('');

  const { getProviderConfig } = useModelManager();
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
  }, [hasBatchPending]); // eslint-disable-line react-hooks/exhaustive-deps

  // isProcessing 自動切換
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

  const handleUploadChange = useCallback(({ fileList: newFileList }) => {
    const updatedList = newFileList.map((f) => ({
      ...f,
      status: f.status || 'waiting',
      percent: f.percent === undefined ? 0 : f.percent,
      statusText: '等待處理',
    }));
    setFileList(updatedList);
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
      const res = await api.transcription.cancel(uid, target.provider);
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

  // 啟動轉錄：解析 provider/apiKey/prompt 後分派給 hook
  const handleStartTranscription = useCallback(async () => {
    const provider = findProviderForModel(model);
    if (!provider) {
      message.error(`找不到模型 ${model} 對應的服務商設定。`);
      return;
    }

    const config = await getProviderConfig(provider);
    const apiKey = config?.apiKeys?.[0];
    const prompt = config?.prompt;
    const isLocalProvider = provider.toLowerCase() === 'local';
    if (!apiKey && !isLocalProvider) {
      message.error(`請先在模型管理中為 ${provider} 設定 API 金鑰。`);
      return;
    }
    if (isLocalProvider && useBatchMode) {
      message.error('本地模型不支援批次模式，請改用一般模式。');
      return;
    }

    const defaults = {
      sourceLang: targetLang,
      targetLang: targetTranslateLang,
      multiSpeaker,
      serviceTier: processingMode === 'flex' ? 'flex' : null,
    };

    setIsProcessing(true);

    const runner = useBatchMode ? startBatch : startRegular;
    const result = await runner({ provider, model, apiKey: apiKey || '', prompt, defaults });

    if (result?.skipped) {
      setIsProcessing(false);
      message.warning('沒有等待處理的新檔案！');
    }
  }, [
    model,
    getProviderConfig,
    targetLang,
    targetTranslateLang,
    multiSpeaker,
    processingMode,
    useBatchMode,
    startBatch,
    startRegular,
  ]);

  const value = {
    fileList,
    setFileList,
    targetLang,
    setTargetLang,
    targetTranslateLang,
    setTargetTranslateLang,
    model,
    setModel,
    isProcessing,
    useBatchMode,
    processingMode,
    setProcessingMode,
    multiSpeaker,
    setMultiSpeaker,
    handleUploadChange,
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
