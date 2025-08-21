import React, { createContext, useState, useContext, useEffect, useRef } from 'react';
import { message } from 'antd';
import { modelOptions, findProviderForModel } from '../constants/modelConfig'; // 引入 findProviderForModel
import { useModelManager } from '../components/ModelManager'; // 引入 ModelManager Hook

const API_BASE_URL = 'http://localhost:8000/api/v1';
const WS_BASE_URL = 'ws://localhost:8000/ws';


// 1. 建立 Context
const TranscriptionContext = createContext();

// 方便使用的 Hook
export const useTranscription = () => useContext(TranscriptionContext);

// 2. 建立 Provider 元件
export const TranscriptionProvider = ({ children }) => {
  const [fileList, setFileList] = useState([]);
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [model, setModel] = useState(modelOptions.Google[0].value);
  const [isProcessing, setIsProcessing] = useState(false);
  const { getProviderConfig } = useModelManager();

  // WebSocket 相關
  const [clientId] = useState(() => crypto.randomUUID());
  const socketRef = useRef(null);

  useEffect(() => {
    const ws_url = `${WS_BASE_URL}/${clientId}`;
    const socket = new WebSocket(ws_url);
    socketRef.current = socket;

    socket.onopen = () => console.log('WebSocket 連線成功');
    socket.onclose = () => console.log('WebSocket 連線關閉');
    socket.onerror = (error) => {
      console.error('WebSocket 發生錯誤:', error);
      message.error('無法連接到即時更新服務。');
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('收到 WebSocket 訊息:', data);

      setFileList(currentList =>
        currentList.map(file => {
          if (file.uid === data.file_uid) {
            const updatedFile = {
              ...file,
              statusText: data.status_text
            };

            if (data.status_code === 'COMPLETED' && data.result) {
              updatedFile.status = 'completed';
              updatedFile.result = data.result.transcripts;
              updatedFile.tokens_used = data.result.tokens_used;
              updatedFile.cost = data.result.cost;
              updatedFile.percent = 100;
            } else if (data.status_code === 'FAILED') {
              updatedFile.status = 'error';
              updatedFile.error = data.status_text;
              updatedFile.percent = 100;
            }
            return updatedFile;
          }
          return file;
        })
      );
    };

    return () => {
      socket.close();
    };
  }, [clientId]);
  
  // 監控 fileList 來決定 isProcessing 狀態
  useEffect(() => {
    const stillProcessing = fileList.some(f => f.status === 'processing');
    if (isProcessing && !stillProcessing) {
      setIsProcessing(false);
      message.success('所有任務處理完畢！');
    }
  }, [fileList, isProcessing]);


  // --- 新增: Modal 狀態管理 ---
  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [previewContent, setPreviewContent] = useState('');
  const [previewTitle, setPreviewTitle] = useState('');

  const handleOpenPreview = (record) => {
    setPreviewTitle(`預覽內容: ${record.name}`);
    setPreviewContent(record.result?.txt || '沒有可預覽的文字內容。');
    setIsPreviewModalVisible(true);
  };

  const handleClosePreview = () => {
    setIsPreviewModalVisible(false);
    setPreviewContent('');
    setPreviewTitle('');
  };
  // --------------------------------

  const transcribeFile = async (file, sourceLang, model, provider, apiKey, prompt, file_uid, client_id) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_lang', sourceLang);
    formData.append('model', model);
    formData.append('provider', provider);
    formData.append('api_keys', apiKey);
    formData.append('file_uid', file_uid);
    formData.append('client_id', client_id);
    if (prompt) {
      formData.append('prompt', prompt);
    }

    try {
      const response = await fetch(`${API_BASE_URL}/transcribe`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({})); // Try to parse error response
        throw errorData;
      }
      return await response.json();
    } catch (error) {
      console.error('Error uploading file:', error);
      throw error || new Error('Network error or server is down');
    }
  };

  const transcribeYoutubeUrl = async (url, sourceLang, model, provider, apiKey, prompt, file_uid, client_id) => {
    const payload = {
      youtube_url: url,
      source_lang: sourceLang,
      model: model,
      provider: provider,
      api_keys: apiKey, // 後端模型需要 api_keys
      prompt: prompt,
      file_uid: file_uid,
      client_id: client_id,
    };

    try {
      const response = await fetch(`${API_BASE_URL}/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({})); // Try to parse error response
        throw errorData;
      }
      return await response.json();
    } catch (error) {
      console.error('Error transcribing YouTube URL:', error);
      throw error || new Error('Network error or server is down');
    }
  };

  const downloadFile = (content, fileName, format) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${fileName.split('.').slice(0, -1).join('.')}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleUploadChange = ({ fileList: newFileList }) => {
    const updatedList = newFileList.map(f => ({
      ...f,
      status: f.status || 'waiting',
      percent: f.percent === undefined ? 0 : f.percent,
      statusText: '等待處理', // 新增初始狀態文字
    }));
    setFileList(updatedList);
  };
  
  const handleStartTranscription = async () => {
    const filesToProcess = fileList.filter(f => f.status === 'waiting');
    if (filesToProcess.length === 0) {
      message.warning('沒有等待處理的新檔案！');
      return;
    }

    setIsProcessing(true);
    message.info(`開始處理 ${filesToProcess.length} 個新檔案...`);

    const provider = findProviderForModel(model);
    if (!provider) {
        message.error(`找不到模型 ${model} 對應的服務商設定。`);
        setIsProcessing(false);
        return;
    }

    const config = await getProviderConfig(provider);
    const apiKey = config?.apiKeys?.[0];
    const prompt = config?.prompt;

    if (!apiKey) {
        message.error(`請先在模型管理中為 ${provider} 設定 API 金鑰。`);
        setIsProcessing(false);
        return;
    }

    // 將所有待處理檔案的狀態改為 "processing"
    setFileList(currentList =>
      currentList.map(file =>
        filesToProcess.find(p => p.uid === file.uid)
          ? { ...file, status: 'processing', statusText: '提交任務中...' }
          : file
      )
    );

    // 分別提交所有任務
    filesToProcess.forEach(async (file) => {
      try {
        const response = file.uid.startsWith('yt-')
          ? await transcribeYoutubeUrl(file.name, sourceLang, model, provider, apiKey, prompt, file.uid, clientId)
          : await transcribeFile(file.originFileObj, sourceLang, model, provider, apiKey, prompt, file.uid, clientId);
        
        const { task_uuid } = response;
        // 儲存 task_uuid 並更新狀態
        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid
              ? { ...f, task_uuid: task_uuid, statusText: '任務已提交，排隊等待中...' }
              : f
          )
        );
      } catch (error) {
        const errorMessage = error.detail || (typeof error === 'string' ? error : '提交失敗');
        console.error(`檔案 ${file.name} 提交失敗:`, error);
        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid
              ? { ...f, status: 'error', percent: 100, error: errorMessage, statusText: '提交失敗' }
              : f
          )
        );
      }
    });
  };

  const handleReprocess = (uidToReprocess) => {
    setFileList((currentList) => {
      const fileToReprocess = currentList.find(f => f.uid === uidToReprocess);
      if (fileToReprocess) {
        message.info(`任務 "${fileToReprocess.name}" 已重新加入佇列。`);
      }
      return currentList.map(file => {
          if(file.uid === uidToReprocess) {
              return {
                  ...file,
                  status: 'waiting',
                  percent: 0,
                  tokens_used: 0,
                  cost: 0,
                  result: null,
                  statusText: '等待處理',
                  task_uuid: null,
                  error: null,
              };
          }
          return file;
      });
    });
  };

  const clearAllFiles = () => {
    setFileList([]);
    message.success("已清除所有任務");
  };

  const value = {
    fileList,
    setFileList,
    sourceLang,
    setSourceLang,
    model,
    setModel,
    isProcessing,
    handleUploadChange,
    handleStartTranscription,
    downloadFile,
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
