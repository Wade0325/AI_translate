import React, { useState, createContext, useContext } from 'react';
import { Modal, Input, Button, message } from 'antd';
import {
  MinusCircleOutlined,
  PlusOutlined
} from '@ant-design/icons';
import { useTranscription } from '../context/TranscriptionContext';
import { modelOptions } from '../constants/modelConfig';
import defaultPrompt from '../constants/promptConfig';

// 1. 建立 Context 和自訂 Hook
const ModelManagerContext = createContext(null);
export const useModelManager = () => {
  const context = useContext(ModelManagerContext);
  if (!context) {
    throw new Error('useModelManager must be used within a ModelManagerProvider');
  }
  return context;
};

// Provider 現在只負責提供 Context 和渲染 Modals，不再渲染 UI
const ModelManagerProvider = ({ children }) => {
  // Modal 相關狀態
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState('');
  const [apiKeys, setApiKeys] = useState(['']);
  const [selectedmodel, setSelectedmodel] = useState(undefined);
  const [providerConfigs, setProviderConfigs] = useState({});

  // 編輯參數 Modal 相關狀態
  const [isParamsModalOpen, setIsParamsModalOpen] = useState(false);
  const [editingParamsProvider, setEditingParamsProvider] = useState('');
  const [promptText, setPromptText] = useState('');

  // 先查看使用端是否儲存過轉錄設定，如果沒有則從後端獲取
  const getProviderConfig = async (provider) => {
    // 優先從記憶體快取獲取
    if (providerConfigs[provider]) {
      return providerConfigs[provider];
    }
  
    // 其次從 localStorage 獲取
    try {
      const storedConfigStr = localStorage.getItem(`providerConfig_${provider}`);
      if (storedConfigStr) {
        const storedConfig = JSON.parse(storedConfigStr);
        // 存入記憶體快取並返回
        setProviderConfigs(prev => ({ ...prev, [provider]: storedConfig }));
        return storedConfig;
      }
    } catch (e) {
      console.error('從 localStorage 讀取設定失敗:', e);
    }
  
    // 最後從後端 API 獲取
    try {
      const response = await fetch('/api/v1/setting/models/' + provider);
      if (response.ok) {
        const data = await response.json();
        if (data) {
          // 存入記憶體快取和 localStorage
          setProviderConfigs(prev => ({ ...prev, [provider]: data }));
          try {
            localStorage.setItem(`providerConfig_${provider}`, JSON.stringify(data));
          } catch (e) {
            console.error('寫入 localStorage 失敗:', e);
          }
          return data;
        }
      }
      return null; // 後端無資料
    } catch (error) {
      console.error(`從後端獲取 ${provider} 設定時發生網路錯誤:`, error);
      message.error(`獲取 ${provider} 設定失敗`);
      return null;
    }
  };

  // 統一的資料儲存函式
  const saveProviderConfig = async (provider, partialConfig) => {
    message.loading({ content: `正在保存 ${provider} 的設定...`, key: 'saveConfig' });
    
    const latestConfig = await getProviderConfig(provider) || {};

    const payload = {
      ...latestConfig,
      ...partialConfig,
      provider: provider,
      apiKeys: partialConfig.apiKeys || latestConfig.apiKeys || [''],
      model: partialConfig.model || latestConfig.model || modelOptions[provider]?.[0]?.value,
    };
    
    // 1. 模型設定請求
    try {
      const response = await fetch('/api/v1/setting/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        message.error({ content: `後端保存失敗: ${errorData.detail || '未知錯誤'}`, key: 'saveConfig' });
        return false;
      }

      const result = await response.json();
      const updatedConfig = result.data_received || payload;
      
      // 2. 儲存到 localStorage
      try {
        localStorage.setItem(`providerConfig_${provider}`, JSON.stringify(updatedConfig));
      } catch (e) {
        console.error('寫入 localStorage 失敗:', e);
        message.warn('設定已保存到伺服器，但本地儲存失敗。');
      }

      // 3. 更新 React 狀態 (記憶體快取)
      setProviderConfigs(prev => ({ ...prev, [provider]: updatedConfig }));

      message.success({ content: '設定保存成功！', key: 'saveConfig' });
      return true;

    } catch (error) {
      message.error({ content: `保存時發生網路錯誤: ${error.message}`, key: 'saveConfig' });
      return false;
    }
  };

  // handleEditProvider
  const handleEditProvider = async (provider) => {
    setEditingProvider(provider);
    const config = await getProviderConfig(provider);
    
    if (config) {
      setApiKeys(config.apiKeys && config.apiKeys.length > 0 ? config.apiKeys : ['']);
      setSelectedmodel(config.model);
    } else {
      // 如果後端沒有這個設定，則重設為空狀態
      setApiKeys(['']);
      setSelectedmodel(modelOptions[provider]?.[0]?.value || undefined);
    }

    setIsModalOpen(true);
  };

  // handleOk 現在只負責調用統一的儲存函式
  const handleOk = async () => {
    const validApiKeys = apiKeys.filter(key => key.trim() !== '');
    const success = await saveProviderConfig(editingProvider, {
      apiKeys: validApiKeys,
      model: selectedmodel,
    });
    if (success) {
      setIsModalOpen(false);
    }
  };

  // handleCancel
  const handleCancel = () => {
    setIsModalOpen(false);
  };
  
  // 處理特定索引的 API Key 輸入變更
  const handleApiKeyChange = (index, event) => {
    const newApiKeys = [...apiKeys];
    newApiKeys[index] = event.target.value;
    setApiKeys(newApiKeys);
  };

  // 添加一個新的 API Key 輸入框
  const addApiKeyInput = () => {
    setApiKeys([...apiKeys, '']);
  };

  // 移除特定索引的 API Key 輸入框
  const removeApiKeyInput = (index) => {
    const newApiKeys = apiKeys.filter((_, i) => i !== index);
    setApiKeys(newApiKeys.length > 0 ? newApiKeys : ['']); 
  };

  // handleEditProviderParams 現在也極其簡潔
  const handleEditProviderParams = async (provider) => {
    setEditingParamsProvider(provider);
    const config = await getProviderConfig(provider);
    // 如果 config.prompt 是 undefined 或 null，則使用 defaultPrompt
    setPromptText(config?.prompt ?? defaultPrompt);
    setIsParamsModalOpen(true);
  };

  // handleParamsOk 現在也只負責調用統一的儲存函式
  const handleParamsOk = async () => {
    const success = await saveProviderConfig(editingParamsProvider, {
      prompt: promptText,
    });
    if (success) {
      setIsParamsModalOpen(false);
    }
  };

  // handleParamsCancel (保持不變)
  const handleParamsCancel = () => {
    setIsParamsModalOpen(false);
  };
  
  // handleTestProvider 也使用統一的獲取函式
  const handleTestProvider = async (provider) => {
    message.loading({ content: `正在測試 ${provider} API...`, key: 'testInterface' });

    const config = await getProviderConfig(provider);
    const apiKeysToTest = config?.apiKeys?.filter(key => key) || [];

    if (apiKeysToTest.length === 0) {
      message.error({ content: '沒有可用的 API 金鑰來進行測試。', key: 'testInterface' });
      return;
    }

    try {
      const response = await fetch('/api/v1/setting/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: provider,
          apiKeys: apiKeysToTest,
          model: config.model,
        }),
      });

      const result = await response.json();

      if (response.ok) {
        console.log(`API ${provider} 測試結果:`, result);
        if (result.success) {
          message.success({ content: result.message, key: 'testInterface', duration: 5 });
        } else {
          message.error({ content: `${result.message}`, key: 'testInterface', duration: 5 });
        }
      } else {
        console.error(`API ${provider} 測試失敗:`, result);
        const errorMessage = result.message || '收到錯誤回應，但無法讀取詳細資訊。';
        message.error({
          content: `${provider} API測試失敗: ${errorMessage}`,
          key: 'testInterface',
          duration: 6
        });
      }
    } catch (error) {
      console.error(`測試API ${provider} 時發生網絡錯誤:`, error);
      message.error({ content: `測試 ${provider} API時發生錯誤: ${error.message || '網絡問題'}`, key: 'testInterface', duration: 5 });
    }
  };

  const contextValue = {
    handleEditProvider,
    handleEditProviderParams,
    handleTestProvider,
    getProviderConfig, // <-- 新增匯出
  };

  return (
    <ModelManagerContext.Provider value={contextValue}>
      {children}

      {/* 編輯API Modal */}
      <Modal
        title={`編輯API - ${editingProvider}`}
        open={isModalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        okText="保存"
        cancelText="關閉"
        width={800}
        destroyOnHidden
      >
        <div style={{ marginBottom: '24px' }}>
          <div style={{ marginBottom: '8px', fontWeight: 500 }}>API金鑰</div>
          {/* <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: '12px', marginBottom: '12px' }}>
            請逐行輸入API金鑰。系統將按從上到下的順序嘗試使用這些密鑰。
          </div> */}
          
          {apiKeys.map((key, index) => (
            <div key={index} style={{ display: 'flex', alignItems: 'center', marginBottom: '8px' }}>
              <Input
                placeholder={`API Key ${index + 1}`}
                value={key}
                onChange={(e) => handleApiKeyChange(index, e)}
                style={{ flexGrow: 1 }}
              />
              {apiKeys.length > 1 && (
                <Button 
                  type="text" 
                  danger 
                  icon={<MinusCircleOutlined />}
                  onClick={() => removeApiKeyInput(index)}
                  style={{ marginLeft: '8px' }}
                />
              )}
            </div>
          ))}
          
          {/* <Button 
            type="dashed" 
            onClick={addApiKeyInput} 
            style={{ width: '100%', marginTop: '8px' }}
            icon={<PlusOutlined />}
          >
            添加更多密鑰
          </Button> */}
        </div>
      </Modal>

      {/* 新增：編輯參數 Modal */}
      <Modal
        title={`編輯參數 - ${editingParamsProvider}`}
        open={isParamsModalOpen}
        onOk={handleParamsOk}
        onCancel={handleParamsCancel}
        okText="保存"
        cancelText="關閉"
        width={700}
        destroyOnHidden
      >
        <div style={{ marginBottom: '24px' }}>
          <div style={{ marginBottom: '8px', fontWeight: 500 }}>提示詞 (Prompt)</div>
          <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: '12px', marginBottom: '12px' }}>
            請輸入您希望模型在處理請求時遵循的系統級指令或提示。
          </div>
          <Input.TextArea
            rows={6}
            placeholder="例如：請將音訊轉錄成逐字稿，並翻譯成中文。"
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
          />
        </div>
      </Modal>
    </ModelManagerContext.Provider>
  );
};

export default ModelManagerProvider;