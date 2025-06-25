import React, { createContext, useState, useContext } from 'react';
import axios from 'axios';
import { message } from 'antd';
import { modelNameOptions } from '../constants/modelConfig';

const API_BASE_URL = 'http://localhost:8000/api/v1';

// 1. 建立 Context
const TranscriptionContext = createContext();

// 方便使用的 Hook
export const useTranscription = () => useContext(TranscriptionContext);

// 2. 建立 Provider 元件
export const TranscriptionProvider = ({ children }) => {
  const [fileList, setFileList] = useState([]);
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [model, setModel] = useState(modelNameOptions.Google[0].value);
  const [isProcessing, setIsProcessing] = useState(false);

  const transcribeFile = async (file, sourceLang, model) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_lang', sourceLang);
    formData.append('model', model);

    try {
      const response = await axios.post('/api/v1/transcribe', formData, {
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
      percent: f.percent === undefined ? 0 : f.percent,
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
          ? { ...file, status: 'processing', percent: 20 }
          : file
      )
    );

    const uploadPromises = filesToProcess.map(async (file) => {
      try {
        const response = await transcribeFile(file.originFileObj, sourceLang, model);
        
        const resultObject = response.transcripts;

        setFileList(currentList => currentList.map(f => 
            f.uid === file.uid 
            ? {
                ...f,
                status: 'completed',
                result: resultObject,
                tokens_used: response.tokens_used,
                cost: response.cost,
                percent: 100,
              }
            : f
        ));
        return { status: 'fulfilled', uid: file.uid };
      } catch (error) {
        console.error(`檔案 ${file.name} 上傳失敗:`, error);
        setFileList(currentList => currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'error', percent: 100 } : f
        ));
        return { status: 'rejected', uid: file.uid, error };
      }
    });

    await Promise.allSettled(uploadPromises);

    setIsProcessing(false);
    message.success('所有新任務處理完畢！');
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
  };

  return (
    <TranscriptionContext.Provider value={value}>
      {children}
    </TranscriptionContext.Provider>
  );
};
