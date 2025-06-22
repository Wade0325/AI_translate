import React, { useState, useEffect, createContext, useContext } from 'react';
import { Card, Row, Col, Typography, Button, Dropdown, Space, Modal, Input, Select, message } from 'antd';
import {
  DownOutlined,
  EditOutlined,
  SlidersOutlined,
  PlayCircleOutlined,
  MinusCircleOutlined,
  PlusOutlined
} from '@ant-design/icons';

const { Title } = Typography;
const { Option } = Select;

// 1. 建立 Context 和自訂 Hook
const ModelManagerContext = createContext(null);
export const useModelManager = () => {
  const context = useContext(ModelManagerContext);
  if (!context) {
    throw new Error('useModelManager must be used within a ModelManagerProvider');
  }
  return context;
};

const EnhancedCardHeader = ({ mainTitle, subtitle, extraContent }) => {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      width: '100%',
      padding: '8px 0',
    }}>
      {/* 左側文字區域 (主標題 + 副標題) */}
      <div>
        <div style={{
          fontSize: '16px',
          fontWeight: 600,
          margin: 0,
          lineHeight: 1.5,
          color: 'rgba(0, 0, 0, 0.88)'
        }}>
          {mainTitle}
        </div>
        {subtitle && (
          <div style={{
            fontSize: '12px',
            fontWeight: 400,
            color: 'rgba(0, 0, 0, 0.65)',
            margin: 0,
            marginTop: '2px',
            lineHeight: 1.4,
            whiteSpace: 'normal',
            overflowWrap: 'break-word',
          }}>
            {subtitle}
          </div>
        )}
      </div>
      {/* 右側按鈕區域 - 直接放置 extraContent */}
      {extraContent}
    </div>
  );
};

// 將 Dashboard UI 導出，以便在主頁面使用
export const ModelManagerDashboard = () => {
  const { getDropdownMenuConfig } = useModelManager();

  const dropdownButtonStyle = {
    minWidth: '130px',
    textAlign: 'left',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  };

  return (
    <div>
      <Title level={2} style={{ marginBottom: '24px' }}>
        模型管理中心
      </Title>
      
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={8}>
          <Card
            title={
              <EnhancedCardHeader
                mainTitle="本地模型"
                subtitle="管理本地部署的語言模型，包括模型配置、性能監控等功能。"
                extraContent={null} 
              />
            }
            hoverable
          >
            <Dropdown 
              menu={getDropdownMenuConfig('SakuraLLM')}
              trigger={['click']}
              transitionName=""
            >
              <Button style={dropdownButtonStyle}>
                SakuraLLM <DownOutlined />
              </Button>
            </Dropdown>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={8}>
          <Card
            title={
              <EnhancedCardHeader
                mainTitle="線上模型"
                subtitle="連接各種線上 AI 服務，如 OpenAI、Claude、Google 等第三方模型服務。"
                extraContent={null}
              />
            }
            hoverable
          >
            <Space wrap size={[12, 12]} style={{ marginBottom: '16px' }}>
              <Dropdown 
                menu={getDropdownMenuConfig('Google')}
                trigger={['click']}
                transitionName=""
              >
                <Button style={dropdownButtonStyle}>
                  Google <DownOutlined />
                </Button>
              </Dropdown>
              <Dropdown 
                menu={getDropdownMenuConfig('OpenAI')}
                trigger={['click']}
                transitionName=""
              >
                <Button style={dropdownButtonStyle}>
                  OpenAI <DownOutlined />
                </Button>
              </Dropdown>
              <Dropdown 
                menu={getDropdownMenuConfig('Claude')}
                trigger={['click']}
                transitionName=""
              >
                <Button style={dropdownButtonStyle}>
                  Claude <DownOutlined />
                </Button>
              </Dropdown>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
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

  // 卡片內容中的下拉選單的樣式
  const dropdownButtonStyle = {
    minWidth: '130px',
    textAlign: 'left',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  };

  // 定義模型名稱選項
  const modelNameOptions = {
    Google: [
      { value: 'gemini-2.5-pro-exp-03-25', label: 'gemini-2.5-pro-exp-03-25' },
      { value: 'gemini-2.5-flash-preview-05-20', label: 'gemini-2.5-flash-preview-05-20' },
      { value: 'text-bison-001', label: 'text-bison-001' },
    ],
    OpenAI: [
      { value: 'gpt-4-turbo', label: 'gpt-4-turbo' },
      { value: 'gpt-4', label: 'gpt-4' },
      { value: 'gpt-3.5-turbo', label: 'gpt-3.5-turbo' },
    ],
    Claude: [
      { value: 'claude-3-opus-20240229', label: 'claude-3-opus-20240229' },
      { value: 'claude-3-sonnet-20240229', label: 'claude-3-sonnet-20240229' },
      { value: 'claude-2.1', label: 'claude-2.1' },
    ]
  };

  const getCurrentModelOptions = () => {
    return modelNameOptions[editingInterfaceName] || [];
  };

  // 修改 getDropdownMenuConfig 以便在點擊時打開 Modal
  const getDropdownMenuConfig = (interfaceName) => ({
    items: [
      {
        key: 'edit-interface',
        icon: <EditOutlined />,
        label: '編輯接口',
        onClick: () => handleEditInterface(interfaceName)
      },
      { type: 'divider' },
      {
        key: 'edit-params',
        icon: <SlidersOutlined />,
        label: '編輯參數',
        onClick: () => handleEditParams(interfaceName)
      },
      { type: 'divider' },
      {
        key: 'test-interface',
        icon: <PlayCircleOutlined />,
        label: '測試接口',
        onClick: () => handleTestInterface(interfaceName)
      }
    ]
  });

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
      const response = await fetch(`http://localhost:8000/api/v1/model-manager/setting/${interfaceName}`);
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
      const response = await fetch('http://localhost:8000/api/v1/model-manager/setting', {
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

  // 簡化所有事件處理函式

  // handleEditInterface
  const handleEditInterface = async (interfaceName) => {
    setEditingInterfaceName(interfaceName);
    const config = await getInterfaceConfig(interfaceName);
    
    const defaultModelName = modelNameOptions[interfaceName]?.[0]?.value;

    setApiKeys(config?.apiKeys && config.apiKeys.length > 0 ? config.apiKeys : ['']);
    setSelectedModelName(config?.modelName || defaultModelName);
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
    message.loading({ content: `正在測試 ${interfaceName} 接口...`, key: 'testInterface' });

    const config = await getInterfaceConfig(interfaceName);
    const apiKeysToTest = config?.apiKeys?.filter(key => key) || [];

    if (apiKeysToTest.length === 0) {
      message.error({ content: '沒有可用的 API 金鑰來進行測試。', key: 'testInterface' });
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/api/v1/model-manager/test', {
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
        console.log(`接口 ${interfaceName} 測試結果:`, result);
        if (result.success) {
          message.success({ content: result.message, key: 'testInterface', duration: 5 });
        } else {
          message.error({ content: `${result.message}`, key: 'testInterface', duration: 5 });
        }
      } else {
        console.error(`接口 ${interfaceName} 測試失敗:`, result);
        const errorMessage = result.message || '收到錯誤回應，但無法讀取詳細資訊。';
        message.error({
          content: `${interfaceName} 接口測試失敗: ${errorMessage}`,
          key: 'testInterface',
          duration: 6
        });
      }
    } catch (error) {
      console.error(`測試接口 ${interfaceName} 時發生網絡錯誤:`, error);
      message.error({ content: `測試 ${interfaceName} 接口時發生錯誤: ${error.message || '網絡問題'}`, key: 'testInterface', duration: 5 });
    }
  };

  // 透過 Context 提供的數值
  const contextValue = {
    handleEditInterface,
    handleEditParams,
    handleTestInterface,
    getDropdownMenuConfig,
    interfaceConfigs,
    // 將當前正在編輯的服務商名稱也傳遞出去，方便外部元件使用
    selectedProvider: editingInterfaceName || editingParamsInterfaceName,
  };

  return (
    <ModelManagerContext.Provider value={contextValue}>
      {children}

      {/* 編輯接口 Modal */}
      <Modal
        title={`編輯接口 - ${editingInterfaceName}`}
        open={isModalOpen}
        onOk={handleOk}
        onCancel={handleCancel}
        okText="保存"
        cancelText="關閉"
        width={800}
        destroyOnHidden
      >
        <div style={{ marginBottom: '24px' }}>
          <div style={{ marginBottom: '8px', fontWeight: 500 }}>接口密鑰 (按使用順序排列)</div>
          <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: '12px', marginBottom: '12px' }}>
            請逐行輸入接口密鑰。系統將按從上到下的順序嘗試使用這些密鑰。
          </div>
          
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
          
          <Button 
            type="dashed" 
            onClick={addApiKeyInput} 
            style={{ width: '100%', marginTop: '8px' }}
            icon={<PlusOutlined />}
          >
            添加更多密鑰
          </Button>
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