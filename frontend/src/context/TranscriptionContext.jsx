import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { modelOptions, findProviderForModel } from '../constants/modelConfig';
import { useModelManager } from '../components/ModelManager';
import { useTranscriptionSocket } from '../hooks/useTranscriptionSocket';
import { useUploadQueue } from '../hooks/useUploadQueue';
import { useDownloadBundle } from '../hooks/useDownloadBundle';

const TranscriptionContext = createContext(null);

export const useTranscription = () => {
  const ctx = useContext(TranscriptionContext);
  if (!ctx) {
    throw new Error('useTranscription must be used within TranscriptionProvider');
  }
  return ctx;
};

export const TranscriptionProvider = ({ children }) => {
  // ---- 全域轉錄設定 ----
  const [fileList, setFileList] = useState([]);
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [targetTranslateLang, setTargetTranslateLang] = useState(null);
  const [model, setModel] = useState(modelOptions.Google[0].value);
  const [isProcessing, setIsProcessing] = useState(false);
  // 'standard' | 'flex' | 'batch'
  const [processingMode, setProcessingMode] = useState('batch');
  const [multiSpeaker, setMultiSpeaker] = useState(false);

  // 相容舊 API
  const useBatchMode = processingMode === 'batch';
  const setUseBatchMode = useCallback(
    (v) => setProcessingMode(v ? 'batch' : 'standard'),
    []
  );

  // ---- Modal 狀態 ----
  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [previewContent, setPreviewContent] = useState('');
  const [previewTitle, setPreviewTitle] = useState('');

  // ---- 服務組合 ----
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

  // ---- isProcessing 自動切換 ----
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

      if (failed > 0 && completed === 0) {
        message.error(`${failed} 個任務失敗`);
      } else if (failed > 0) {
        message.warning(`完成 ${completed} 個，${failed} 個失敗`);
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

  // ---- 啟動轉錄：解析 provider/apiKey/prompt 後分派給 hook ----
  const handleStartTranscription = useCallback(async () => {
    const provider = findProviderForModel(model);
    if (!provider) {
      message.error(`找不到模型 ${model} 對應的服務商設定。`);
      return;
    }

    const config = await getProviderConfig(provider);
    const apiKey = config?.apiKeys?.[0];
    const prompt = config?.prompt;
    if (!apiKey) {
      message.error(`請先在模型管理中為 ${provider} 設定 API 金鑰。`);
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
    const result = await runner({ provider, model, apiKey, prompt, defaults });

    if (result?.skipped) {
      setIsProcessing(false);
      if (result.reason === 'no-files' || result.skipped) {
        message.warning(
          useBatchMode
            ? '沒有等待處理的新檔案！（批次模式不支援 YouTube 連結）'
            : '沒有等待處理的新檔案！'
        );
      }
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
    setUseBatchMode,
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
