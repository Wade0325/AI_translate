import React, { useState, createContext, useContext } from 'react';
import { Modal, Input, Button, message } from 'antd';
import {
  MinusCircleOutlined,
  PlusOutlined
} from '@ant-design/icons';
import { useTranscription } from '../context/TranscriptionContext';
import { modelNameOptions } from '../constants/modelConfig';

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
  const [editingInterfaceName, setEditingInterfaceName] = useState('');
  const [apiKeys, setApiKeys] = useState(['']);
  const [selectedModelName, setSelectedModelName] = useState(undefined);
  const [interfaceConfigs, setInterfaceConfigs] = useState({});

  // 編輯參數 Modal 相關狀態
  const [isParamsModalOpen, setIsParamsModalOpen] = useState(false);
  const [editingParamsInterfaceName, setEditingParamsInterfaceName] = useState('');
  const [promptText, setPromptText] = useState('');

  // 資料獲取函式
  const getInterfaceConfig = async (interfaceName) => {
    // 檢查本地快取
    const cachedConfig = interfaceConfigs[interfaceName];
    if (cachedConfig) {
      return cachedConfig;
    }

    // 如果快取沒有，則從後端獲取
    try {
      console.log(`統一獲取: ${interfaceName} (從後端)`);
      const response = await fetch('/api/v1/model-manager/setting/' + interfaceName);
      if (response.ok) {
        const data = await response.json();
        if (data) {
          // 存入快取並返回
          setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: data }));
          return data;
        }
      }
      // 如果後端沒資料或請求失敗，返回 null
      return null;
    } catch (error) {
      console.error(`獲取 ${interfaceName} 設定時發生網路錯誤:`, error);
      message.error(`獲取 ${interfaceName} 設定失敗`);
      return null;
    }
  };

  // 統一的資料儲存函式
  const saveInterfaceConfig = async (interfaceName, partialConfig) => {
    message.loading({ content: `正在保存 ${interfaceName} 的設定...`, key: 'saveConfig' });
    
    // 先獲取當前最新的完整設定，防止資料覆寫
    const latestConfig = await getInterfaceConfig(interfaceName) || {};

    // 合併舊設定與要更新的部分設定
    const payload = {
      ...latestConfig,          // 包含舊的 prompt, apiKeys, modelName 等
      ...partialConfig,         // 用新的部分覆蓋舊的
      interfaceName: interfaceName, // 確保 interfaceName 正確
      // 如果 apiKeys 或 modelName 在 partialConfig 中是 undefined，它會自動使用 latestConfig 中的值
      apiKeys: partialConfig.apiKeys || latestConfig.apiKeys || [''],
      modelName: partialConfig.modelName || latestConfig.modelName || modelNameOptions[interfaceName]?.[0]?.value,
    };
    
    // 發送請求
    try {
      const response = await fetch('/api/v1/model-manager/setting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        const result = await response.json();
        message.success({ content: '設定保存成功！', key: 'saveConfig' });
        setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: result.data_received || payload }));
        return true;
      } else {
        const errorData = await response.json().catch(() => ({}));
        message.error({ content: `保存失敗: ${errorData.detail || '未知錯誤'}`, key: 'saveConfig' });
        return false;
      }
    } catch (error) {
      message.error({ content: `保存時發生網路錯誤: ${error.message}`, key: 'saveConfig' });
      return false;
    }
  };

  // handleEditInterface
  const handleEditInterface = async (interfaceName) => {
    setEditingInterfaceName(interfaceName);
    console.log('當前點擊 "編輯API" 時，interfaceName 的值是:', interfaceName);
    // 呼叫統一的資料獲取函式
    const config = await getInterfaceConfig(interfaceName);
    console.log('當前點擊 "編輯API" 時，config 的值是:', config);
    // 如果從後端獲取到了設定，則用它來填充 Modal
    if (config) {
      setApiKeys(config.apiKeys && config.apiKeys.length > 0 ? config.apiKeys : ['']);
      setSelectedModelName(config.modelName);
    } else {
      // 如果後端沒有這個設定，則重設為空狀態
      setApiKeys(['']);
      setSelectedModelName(undefined);
    }

    setIsModalOpen(true);
  };

  // handleOk 現在只負責調用統一的儲存函式
  const handleOk = async () => {
    const validApiKeys = apiKeys.filter(key => key.trim() !== '');
    const success = await saveInterfaceConfig(editingInterfaceName, {
      apiKeys: validApiKeys,
      modelName: selectedModelName,
    });
    if (success) {
      setIsModalOpen(false);
    }
  };

  // handleCancel (保持不變)
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

  // handleEditParams 現在也極其簡潔
  const handleEditParams = async (interfaceName) => {
    setEditingParamsInterfaceName(interfaceName);
    const config = await getInterfaceConfig(interfaceName);
    setPromptText(config?.prompt || '');
    setIsParamsModalOpen(true);
  };

  // handleParamsOk 現在也只負責調用統一的儲存函式
  const handleParamsOk = async () => {
    const success = await saveInterfaceConfig(editingParamsInterfaceName, {
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
  
  // handleTestInterface 也使用統一的獲取函式
  const handleTestInterface = async (interfaceName) => {
    message.loading({ content: `正在測試 ${interfaceName} API...`, key: 'testInterface' });

    const config = await getInterfaceConfig(interfaceName);
    const apiKeysToTest = config?.apiKeys?.filter(key => key) || [];

    if (apiKeysToTest.length === 0) {
      message.error({ content: '沒有可用的 API 金鑰來進行測試。', key: 'testInterface' });
      return;
    }

    try {
      const response = await fetch('/api/v1/model-manager/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          interfaceName: interfaceName,
          apiKeys: apiKeysToTest,
          modelName: config.modelName,
        }),
      });

      const result = await response.json();

      if (response.ok) {
        console.log(`API ${interfaceName} 測試結果:`, result);
        if (result.success) {
          message.success({ content: result.message, key: 'testInterface', duration: 5 });
        } else {
          message.error({ content: `${result.message}`, key: 'testInterface', duration: 5 });
        }
      } else {
        console.error(`API ${interfaceName} 測試失敗:`, result);
        const errorMessage = result.message || '收到錯誤回應，但無法讀取詳細資訊。';
        message.error({
          content: `${interfaceName} API測試失敗: ${errorMessage}`,
          key: 'testInterface',
          duration: 6
        });
      }
    } catch (error) {
      console.error(`測試API ${interfaceName} 時發生網絡錯誤:`, error);
      message.error({ content: `測試 ${interfaceName} API時發生錯誤: ${error.message || '網絡問題'}`, key: 'testInterface', duration: 5 });
    }
  };

  const contextValue = {
    handleEditInterface,
    handleEditParams,
    handleTestInterface,
  };

  return (
    <ModelManagerContext.Provider value={contextValue}>
      {children}

      {/* 編輯API Modal */}
      <Modal
        title={`編輯API - ${editingInterfaceName}`}
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
                placeholder={`密鑰 ${index + 1} (例如 sk-...)`}
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
        title={`編輯參數 - ${editingParamsInterfaceName}`}
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