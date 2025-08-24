import React, { createContext, useState, useContext, useEffect, useRef } from 'react';
import { message } from 'antd';
import JSZip from 'jszip';
import { modelOptions, findProviderForModel } from '../constants/modelConfig'; // 引入 findProviderForModel
import { useModelManager } from '../components/ModelManager'; // 引入 ModelManager Hook

const API_BASE_URL = 'http://localhost:8000/api/v1';
const WS_BASE_URL = 'ws://localhost:8000/api/v1/ws';


// 1. 建立 Context
const TranscriptionContext = createContext();

// 方便使用的 Hook
export const useTranscription = () => useContext(TranscriptionContext);

// 2. 建立 Provider 元件
export const TranscriptionProvider = ({ children }) => {
  const [fileList, setFileList] = useState([]);
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [model, setModel] = useState(modelOptions.Google[0].value);
  const [isProcessing, setIsProcessing] = useState(false);
  const { getProviderConfig } = useModelManager();

  // 【修改 1】移除舊的 WebSocket 相關 state 和 ref
  // const [clientId] = useState(() => crypto.randomUUID());
  // const socketRef = useRef(null);
  const activeSockets = useRef({}); // 用於管理所有活躍的 socket

  // 【修改 2】移除舊的、建立單一 WebSocket 的 useEffect
  /* 
  useEffect(() => {
    // ... 舊的 WebSocket 邏輯已移除 ...
  }, [clientId]);
  */
  
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

  // 【修改 3】移除舊的、基於 HTTP 的 transcribeFile 和 transcribeYoutubeUrl 函式
  /*
  const transcribeFile = async (...) => { ... };
  const transcribeYoutubeUrl = async (...) => { ... };
  */

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

  // 修改：下載全部完成檔案並打包成ZIP的函式
  const downloadAllFiles = async (format) => {
    const completedFiles = fileList.filter(f => f.status === 'completed' && f.result);
    
    if (completedFiles.length === 0) {
      message.warning('沒有已完成的檔案可以下載！');
      return;
    }

    try {
      message.loading({ content: '正在打包檔案...', key: 'zipDownload' });
      
      const zip = new JSZip();
      const formatUpper = format.toUpperCase();
      
      // 將所有檔案加入 ZIP
      completedFiles.forEach(file => {
        const content = file.result[format] || '';
        if (content) {
          const fileName = `${file.name.split('.').slice(0, -1).join('.')}.${format}`;
          zip.file(fileName, content);
        }
      });

      // 生成 ZIP 檔案
      const zipBlob = await zip.generateAsync({ type: 'blob' });
      
      // 下載 ZIP 檔案
      const url = URL.createObjectURL(zipBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `transcripts_${formatUpper}_${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      message.success({ 
        content: `已成功下載 ${completedFiles.length} 個 ${formatUpper} 檔案的壓縮包！`, 
        key: 'zipDownload' 
      });
      
    } catch (error) {
      console.error('打包下載失敗:', error);
      message.error({ 
        content: '打包下載失敗，請稍後再試', 
        key: 'zipDownload' 
      });
    }
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
    const filesToProcess = fileList.filter(f => 
      (f.status === 'waiting' || f.status === 'error') && f.originFileObj
    );
    const youtubeUrlsToProcess = fileList.filter(f => 
      (f.status === 'waiting' || f.status === 'error') && !f.originFileObj && f.name.includes('youtube')
    );
    
    if (filesToProcess.length === 0 && youtubeUrlsToProcess.length === 0) {
      message.warning('沒有等待處理的新檔案！');
      return;
    }

    setIsProcessing(true);
    
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

    // 更新狀態為上傳中
    setFileList(currentList =>
      currentList.map(file =>
        [...filesToProcess, ...youtubeUrlsToProcess].find(p => p.uid === file.uid)
          ? { ...file, status: 'processing', statusText: '正在上傳檔案...' }
          : file
      )
    );

    // 處理一般檔案上傳
    for (const file of filesToProcess) {
      try {
        // 上傳檔案到服務器
        const formData = new FormData();
        formData.append('file', file.originFileObj);
        
        const response = await fetch(`${API_BASE_URL}/upload`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          throw new Error('檔案上傳失敗');
        }

        const { filename: serverFilename } = await response.json();
        
        // 更新檔案狀態並建立 WebSocket
        setFileList(currentList => currentList.map(f =>
          f.uid === file.uid ? { ...f, statusText: '正在建立連線...', serverFilename } : f
        ));

        // 建立 WebSocket 連接
        const socket = new WebSocket(`${WS_BASE_URL}/${file.uid}`);
        activeSockets.current[file.uid] = socket;

        socket.onopen = () => {
          console.log(`WebSocket for ${file.name} (${file.uid}) connected.`);
          setFileList(currentList => currentList.map(f =>
            f.uid === file.uid ? { ...f, statusText: '連線成功，正在提交任務...' } : f
          ));
          
          const payload = {
            filename: serverFilename, // 使用服務器返回的檔案名
            original_filename: file.name,
            provider: provider,
            model: model,
            api_keys: apiKey,
            source_lang: targetLang,
            prompt: prompt,
          };
          socket.send(JSON.stringify(payload));
        };

        socket.onmessage = (event) => {
          const data = JSON.parse(event.data);
          console.log(`Message for ${file.name}:`, data);
          setFileList(currentList =>
            currentList.map(f => {
              if (f.uid === data.file_uid) {
                const updatedFile = {
                  ...f,
                  statusText: data.status_text,
                  task_uuid: data.task_uuid,
                };
                if (data.status_code === 'COMPLETED') {
                  updatedFile.status = 'completed';
                  updatedFile.percent = 100;
                  updatedFile.result = data.result?.transcripts;
                  updatedFile.tokens_used = data.result?.tokens_used;
                  updatedFile.cost = data.result?.cost;
                } else if (data.status_code === 'FAILED') {
                  updatedFile.status = 'error';
                  updatedFile.percent = 100;
                  updatedFile.error = data.status_text;
                }
                return updatedFile;
              }
              return f;
            })
          );
        };

        socket.onerror = (error) => {
          console.error(`WebSocket error for ${file.name}:`, error);
          message.error(`檔案 ${file.name} 的連線發生錯誤。`);
          setFileList(currentList => currentList.map(f =>
              f.uid === file.uid ? { ...f, status: 'error', percent: 100, error: '連線錯誤', statusText: '連線失敗' } : f
          ));
        };

        socket.onclose = () => {
          console.log(`WebSocket for ${file.name} (${file.uid}) closed.`);
          delete activeSockets.current[file.uid];
        };
        
      } catch (error) {
        console.error(`上傳檔案 ${file.name} 失敗:`, error);
        setFileList(currentList => currentList.map(f =>
          f.uid === file.uid ? { ...f, status: 'error', statusText: '上傳失敗', percent: 100 } : f
        ));
      }
    }

    // 處理 YouTube URL（如果有的話）
    youtubeUrlsToProcess.forEach((file) => {
      // YouTube URL 直接使用 WebSocket，不需要上傳
      const socket = new WebSocket(`${WS_BASE_URL}/${file.uid}`);
      activeSockets.current[file.uid] = socket;

      socket.onopen = () => {
        console.log(`WebSocket for ${file.name} (${file.uid}) connected.`);
        setFileList(currentList => currentList.map(f =>
          f.uid === file.uid ? { ...f, statusText: '連線成功，正在提交任務...' } : f
        ));
        
        const payload = {
          filename: file.name, // 使用檔案名稱
          original_filename: file.name,
          provider: provider,
          model: model,
          api_keys: apiKey,
          source_lang: targetLang,
          prompt: prompt,
        };
        socket.send(JSON.stringify(payload));
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(`Message for ${file.name}:`, data);
        setFileList(currentList =>
          currentList.map(f => {
            if (f.uid === data.file_uid) {
              const updatedFile = {
                ...f,
                statusText: data.status_text,
                task_uuid: data.task_uuid,
              };
              if (data.status_code === 'COMPLETED') {
                updatedFile.status = 'completed';
                updatedFile.percent = 100;
                updatedFile.result = data.result?.transcripts;
                updatedFile.tokens_used = data.result?.tokens_used;
                updatedFile.cost = data.result?.cost;
              } else if (data.status_code === 'FAILED') {
                updatedFile.status = 'error';
                updatedFile.percent = 100;
                updatedFile.error = data.status_text;
              }
              return updatedFile;
            }
            return f;
          })
        );
      };

      socket.onerror = (error) => {
        console.error(`WebSocket error for ${file.name}:`, error);
        message.error(`檔案 ${file.name} 的連線發生錯誤。`);
        setFileList(currentList => currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'error', percent: 100, error: '連線錯誤', statusText: '連線失敗' } : f
        ));
      };

      socket.onclose = () => {
        console.log(`WebSocket for ${file.name} (${file.uid}) closed.`);
        delete activeSockets.current[file.uid];
      };
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
    // 關閉所有還在活躍的 WebSocket 連線
    Object.values(activeSockets.current).forEach(socket => socket.close());
    activeSockets.current = {};
    
    setFileList([]);
    message.success("已清除所有任務");
  };

  const value = {
    fileList,
    setFileList,
    targetLang,
    setTargetLang,
    model,
    setModel,
    isProcessing,
    handleUploadChange,
    handleStartTranscription,
    downloadFile,
    downloadAllFiles, // 新增
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
