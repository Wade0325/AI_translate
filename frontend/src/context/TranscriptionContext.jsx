import React, { createContext, useState, useContext } from 'react';
import axios from 'axios';
import { message } from 'antd';

const API_BASE_URL = 'http://localhost:8000/api/v1';

// 1. 建立 Context
const TranscriptionContext = createContext();

// 方便使用的 Hook
export const useTranscription = () => useContext(TranscriptionContext);

// 2. 建立 Provider 元件
export const TranscriptionProvider = ({ children }) => {
  const [fileList, setFileList] = useState([]);
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [model, setModel] = useState('Google');
  const [isProcessing, setIsProcessing] = useState(false);

  const transcribeFile = async (file, sourceLang, model) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_lang', sourceLang);
    formData.append('model', model);

    try {
      const response = await axios.post(`${API_BASE_URL}/transcribe`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return response.data;
    } catch (error) {
      console.error('Error uploading file:', error);
      throw error.response ? error.response.data : new Error('Network error or server is down');
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

    setFileList(currentList =>
      currentList.map(file =>
        filesToProcess.find(p => p.uid === file.uid)
          ? { ...file, status: 'processing' }
          : file
      )
    );

    const uploadPromises = filesToProcess.map(async (file) => {
      try {
        const response = await transcribeFile(file.originFileObj, sourceLang, model);
        
        // 假設後端回應包含一個 transcripts 物件，裡面有多種格式
        const resultObject = response.transcripts;

        setFileList(currentList => currentList.map(f => 
            f.uid === file.uid 
            ? {
                ...f,
                status: 'completed',
                result: resultObject,
                tokens_used: response.tokens_used,
                cost: response.cost,
              }
            : f
        ));
        return { status: 'fulfilled', uid: file.uid };
      } catch (error) {
        console.error(`檔案 ${file.name} 上傳失敗:`, error);
        setFileList(currentList => currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'error' } : f
        ));
        return { status: 'rejected', uid: file.uid, error };
      }
    });

    await Promise.allSettled(uploadPromises);

    setIsProcessing(false);
    message.success('所有新任務處理完畢！');
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
  };

  return (
    <TranscriptionContext.Provider value={value}>
      {children}
    </TranscriptionContext.Provider>
  );
};
