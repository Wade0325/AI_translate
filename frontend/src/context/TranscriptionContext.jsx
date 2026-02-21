import React, { createContext, useState, useContext, useEffect, useRef } from 'react';
import { message } from 'antd';
import JSZip from 'jszip';
import { modelOptions, findProviderForModel } from '../constants/modelConfig';
import { useModelManager } from '../components/ModelManager';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || `${wsProtocol}//${window.location.host}/api/v1/ws`;
const WS_BATCH_URL = import.meta.env.VITE_WS_BATCH_URL || `${wsProtocol}//${window.location.host}/api/v1/batch/ws`;



// 1. 建立 Context
const TranscriptionContext = createContext();

// 方便使用的 Hook
export const useTranscription = () => useContext(TranscriptionContext);

// 2. 建立 Provider 元件
export const TranscriptionProvider = ({ children }) => {
  const [fileList, setFileList] = useState([]);
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [targetTranslateLang, setTargetTranslateLang] = useState(null); // 新增: 翻譯目標語言
  const [model, setModel] = useState(modelOptions.Google[0].value);
  const [isProcessing, setIsProcessing] = useState(false);
  const [useBatchMode, setUseBatchMode] = useState(false);
  const [pendingBatches, setPendingBatches] = useState([]);
  const [isRecovering, setIsRecovering] = useState(false);
  const { getProviderConfig } = useModelManager();

  const activeSockets = useRef({}); // 用於管理所有活躍的 socket

  
  // 監控 fileList 來決定 isProcessing 狀態
  // 使用 ref 來追蹤是否曾經有任務開始處理
  const hasStartedProcessing = useRef(false);

  useEffect(() => {
    const stillProcessing = fileList.some(f => f.status === 'processing');
    
    // 如果有文件正在處理，標記已經開始處理
    if (stillProcessing) {
      hasStartedProcessing.current = true;
    }
    
    // 只有在「曾經開始處理」且「現在沒有處理中的文件」時才顯示完成訊息
    if (isProcessing && hasStartedProcessing.current && !stillProcessing) {
      setIsProcessing(false);
      hasStartedProcessing.current = false; // 重置標記
      message.success('所有任務處理完畢！');
    }
  }, [fileList, isProcessing]);


  // --- 頁面載入時檢查未完成的批次任務 ---
  useEffect(() => {
    const checkPendingBatches = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/batch/pending`);
        if (response.ok) {
          const data = await response.json();
          setPendingBatches(data);
          if (data.length > 0) {
            console.log(`發現 ${data.length} 個未完成的批次任務`);
          }
        }
      } catch (error) {
        console.error('檢查未完成批次任務失敗:', error);
      }
    };
    checkPendingBatches();
  }, []);


  // --- 恢復批次任務 ---
  const recoverBatch = async (batchId) => {
    setIsRecovering(true);
    try {
      // 取得 API Key（使用已儲存的 Google 設定）
      const config = await getProviderConfig('Google');
      const apiKey = config?.apiKeys?.[0];
      if (!apiKey) {
        message.error('請先在模型管理中為 Google 設定 API 金鑰，才能恢復批次任務。');
        setIsRecovering(false);
        return;
      }

      message.loading({ content: '正在恢復批次任務...', key: 'recover', duration: 0 });

      const response = await fetch(`${API_BASE_URL}/batch/${batchId}/recover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_keys: apiKey }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `恢復失敗 (${response.status})`);
      }

      const result = await response.json();

      // 路徑 1：有結果（DB 快速路徑）→ 直接填入
      if (result.files && result.files.length > 0) {
        const recoveredFiles = result.files.map(f => ({
          uid: f.file_uid,
          name: f.original_filename,
          status: f.status === 'COMPLETED' ? 'completed' : 'error',
          percent: 100,
          statusText: f.status === 'COMPLETED' ? '已恢復' : `恢復失敗: ${f.error || '未知錯誤'}`,
          result: f.result?.transcripts || null,
          tokens_used: f.result?.tokens_used || 0,
          cost: f.result?.cost || 0,
          input_cost: f.result?.input_cost || 0,
          output_cost: f.result?.output_cost || 0,
          error: f.error || null,
        }));
        setFileList(prev => [...recoveredFiles, ...prev]);
        setPendingBatches(prev => prev.filter(b => b.batch_id !== batchId));
        const completedCount = result.files.filter(f => f.status === 'COMPLETED').length;
        message.success({ content: `已恢復 ${completedCount} / ${result.files.length} 個檔案`, key: 'recover' });
        setIsRecovering(false);
        return;
      }

      // 路徑 2：空結果（Celery 在背景從 Gemini 恢復）→ 輪詢等待結果
      message.loading({ content: '正在從 Gemini 恢復結果，請稍候...', key: 'recover', duration: 0 });

      // 每 5 秒輪詢一次，直到結果出現在 DB 或超時
      const maxAttempts = 60; // 最多等 5 分鐘
      let attempts = 0;

      const pollForResults = async () => {
        attempts++;
        try {
          const pollResp = await fetch(`${API_BASE_URL}/batch/${batchId}/recover`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_keys: apiKey }),
          });

          if (pollResp.ok) {
            const pollResult = await pollResp.json();
            if (pollResult.files && pollResult.files.length > 0) {
              // 結果到了！
              const recoveredFiles = pollResult.files.map(f => ({
                uid: f.file_uid,
                name: f.original_filename,
                status: f.status === 'COMPLETED' ? 'completed' : 'error',
                percent: 100,
                statusText: f.status === 'COMPLETED' ? '已恢復' : `恢復失敗: ${f.error || '未知錯誤'}`,
                result: f.result?.transcripts || null,
                tokens_used: f.result?.tokens_used || 0,
                cost: f.result?.cost || 0,
                input_cost: f.result?.input_cost || 0,
                output_cost: f.result?.output_cost || 0,
                error: f.error || null,
              }));
              setFileList(prev => [...recoveredFiles, ...prev]);
              setPendingBatches(prev => prev.filter(b => b.batch_id !== batchId));
              const completedCount = pollResult.files.filter(f => f.status === 'COMPLETED').length;
              message.success({ content: `已恢復 ${completedCount} 個檔案的轉錄結果！`, key: 'recover' });
              setIsRecovering(false);
              return;
            }
          }
        } catch (e) {
          console.log('Poll attempt failed:', e);
        }

        if (attempts < maxAttempts) {
          setTimeout(pollForResults, 5000);
        } else {
          message.warning({ content: '恢復超時，請稍後重新整理頁面再試', key: 'recover' });
          setIsRecovering(false);
        }
      };

      // 第一次等 5 秒讓 Celery 有時間處理
      setTimeout(pollForResults, 5000);

    } catch (error) {
      console.error('恢復批次任務失敗:', error);
      message.error({ content: `恢復失敗: ${error.message}`, key: 'recover' });
      setIsRecovering(false);
    }
  };


  // --- Modal 狀態管理 ---
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
      statusText: '等待處理', // 使用者選擇檔案後在畫面上顯示的初始狀態文字
    }));
    setFileList(updatedList);
  };
  
  // =============================================
  // 一般模式：每個檔案各自建立 WebSocket 連線
  // =============================================
  const handleRegularTranscription = async () => {
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
            target_lang: targetTranslateLang || null, // 輸出語言
            prompt: prompt,
            original_text: file.original_text || null,
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
                  updatedFile.input_cost = data.result?.input_cost;
                  updatedFile.output_cost = data.result?.output_cost;
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
          target_lang: targetTranslateLang || null, // 輸出語言
          prompt: prompt,
          original_text: file.original_text || null,
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
                updatedFile.input_cost = data.result?.input_cost;
                updatedFile.output_cost = data.result?.output_cost;
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

  // =============================================
  // 批次模式：所有檔案共用一個 Batch WebSocket
  // 使用 Gemini Batch API，費用為標準的 50%
  // =============================================
  const handleBatchTranscription = async () => {
    const filesToProcess = fileList.filter(f =>
      (f.status === 'waiting' || f.status === 'error') && f.originFileObj
    );

    if (filesToProcess.length === 0) {
      message.warning('沒有等待處理的新檔案！（批次模式不支援 YouTube 連結）');
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

    // 將所有待處理檔案標記為 processing
    setFileList(currentList =>
      currentList.map(file =>
        filesToProcess.find(p => p.uid === file.uid)
          ? { ...file, status: 'processing', statusText: '正在上傳檔案...' }
          : file
      )
    );

    // 第一步：逐一上傳所有檔案到伺服器
    const uploadedFiles = [];
    for (const file of filesToProcess) {
      try {
        const formData = new FormData();
        formData.append('file', file.originFileObj);

        const response = await fetch(`${API_BASE_URL}/upload`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) throw new Error('檔案上傳失敗');

        const { filename: serverFilename } = await response.json();

        setFileList(currentList => currentList.map(f =>
          f.uid === file.uid
            ? { ...f, statusText: '檔案已上傳，等待批次處理...', serverFilename }
            : f
        ));

        uploadedFiles.push({ ...file, serverFilename });
      } catch (error) {
        console.error(`上傳檔案 ${file.name} 失敗:`, error);
        setFileList(currentList => currentList.map(f =>
          f.uid === file.uid
            ? { ...f, status: 'error', statusText: '上傳失敗', percent: 100 }
            : f
        ));
      }
    }

    if (uploadedFiles.length === 0) {
      message.error('所有檔案上傳失敗，無法啟動批次任務');
      setIsProcessing(false);
      return;
    }

    // 第二步：建立批次 WebSocket 連線
    const batchId = `batch-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const socket = new WebSocket(`${WS_BATCH_URL}/${batchId}`);
    activeSockets.current[batchId] = socket;

    socket.onopen = () => {
      console.log(`Batch WebSocket connected: ${batchId}`);

      setFileList(currentList => currentList.map(f =>
        uploadedFiles.find(uf => uf.uid === f.uid)
          ? { ...f, statusText: '批次任務已提交，等待處理...' }
          : f
      ));

      const payload = {
        files: uploadedFiles.map(f => ({
          filename: f.serverFilename,
          original_filename: f.name,
          file_uid: f.uid,
        })),
        provider,
        model,
        api_keys: apiKey,
        source_lang: targetLang,
        target_lang: targetTranslateLang || null,
        prompt,
      };
      socket.send(JSON.stringify(payload));
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('Batch message:', data);

      // BATCH_SUBMITTED 表示檔案已全部提交至 Gemini，可以釋放前端 UI
      if (data.status_code === 'BATCH_SUBMITTED') {
        console.log('Batch submitted to Gemini:', data.status_text);
        setIsProcessing(false);
        hasStartedProcessing.current = false;
        // 將所有仍在 processing 的批次檔案標記為 batch_pending（不再卡住 UI）
        setFileList(currentList =>
          currentList.map(f =>
            f.status === 'processing' && uploadedFiles.find(uf => uf.uid === f.uid)
              ? { ...f, status: 'batch_pending', statusText: data.status_text }
              : f
          )
        );
        message.success('批次任務已提交，可繼續其他操作。結果將自動更新或可稍後恢復。');
        return;
      }

      // BATCH_COMPLETED 表示整個批次結束，不需要更新個別檔案
      if (data.status_code === 'BATCH_COMPLETED') {
        console.log('Batch job completed:', data.status_text);
        return;
      }

      // 有 file_uid 表示是某個檔案的個別更新
      if (data.file_uid) {
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
                updatedFile.input_cost = data.result?.input_cost;
                updatedFile.output_cost = data.result?.output_cost;
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
      } else {
        // 沒有 file_uid 的是整體批次進度更新，同步到所有仍在處理中的檔案
        setFileList(currentList =>
          currentList.map(f => {
            if (f.status === 'processing' && uploadedFiles.find(uf => uf.uid === f.uid)) {
              return { ...f, statusText: data.status_text };
            }
            return f;
          })
        );
      }
    };

    socket.onerror = (error) => {
      console.error('Batch WebSocket error:', error);
      message.error('批次任務連線發生錯誤');
      setFileList(currentList => currentList.map(f =>
        uploadedFiles.find(uf => uf.uid === f.uid) && f.status === 'processing'
          ? { ...f, status: 'error', percent: 100, error: '批次連線錯誤', statusText: '連線失敗' }
          : f
      ));
    };

    socket.onclose = () => {
      console.log(`Batch WebSocket closed: ${batchId}`);
      delete activeSockets.current[batchId];
    };
  };

  // =============================================
  // 分流 Wrapper：根據 useBatchMode 選擇模式
  // =============================================
  const handleStartTranscription = async () => {
    if (useBatchMode) {
      return handleBatchTranscription();
    }
    return handleRegularTranscription();
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
    targetTranslateLang,
    setTargetTranslateLang,
    model,
    setModel,
    isProcessing,
    useBatchMode,
    setUseBatchMode,
    handleUploadChange,
    handleStartTranscription,
    downloadFile,
    downloadAllFiles,
    clearAllFiles,
    handleReprocess,
    pendingBatches,
    isRecovering,
    recoverBatch,
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
