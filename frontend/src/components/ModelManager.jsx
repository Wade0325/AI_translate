import React, { useState, useEffect } from 'react';
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

const ModelManager = () => {
  // Modal 相關狀態
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingInterfaceName, setEditingInterfaceName] = useState('');
  const [apiKeys, setApiKeys] = useState(['']);
  const [selectedModelName, setSelectedModelName] = useState(undefined);
  const [interfaceConfigs, setInterfaceConfigs] = useState({});

  // 新增：編輯參數 Modal 相關狀態
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
      { value: 'gemini-1.0-pro', label: 'gemini-1.0-pro' },
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

  // 修改 handleEditInterface 以從後端獲取數據
  const handleEditInterface = async (interfaceName) => {
    setEditingInterfaceName(interfaceName);
    const defaultModelName = modelNameOptions[interfaceName]?.[0]?.value;

    const cachedConfig = interfaceConfigs[interfaceName];

    if (cachedConfig && cachedConfig.apiKeys !== undefined && cachedConfig.modelName !== undefined) {
        console.log(`Using cached config for ${interfaceName}`);
        setApiKeys(cachedConfig.apiKeys && cachedConfig.apiKeys.length > 0 ? cachedConfig.apiKeys : ['']);
        setSelectedModelName(cachedConfig.modelName);
        setIsModalOpen(true);
        return;
    }

    try {
      console.log(`Fetching configuration for: ${interfaceName}`);
      const response = await fetch(`http://localhost:8000/settings/model_setting/${interfaceName}`);

      if (response.ok) {
        const data = await response.json();
        if (data) {
          console.log('Fetched data from backend:', data);
          setApiKeys(data.apiKeys && data.apiKeys.length > 0 ? data.apiKeys : ['']);
          setSelectedModelName(data.modelName);
          setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: data }));
        } else {
          console.log(`No configuration found in DB for ${interfaceName}, using defaults.`);
          const defaultConfig = {
            interfaceName: interfaceName,
            apiKeys: [''], 
            modelName: defaultModelName, 
            prompt: null 
          };
          setApiKeys(defaultConfig.apiKeys);
          setSelectedModelName(defaultConfig.modelName);
          setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: defaultConfig }));
        }
      } else {
        const errorData = await response.json().catch(() => ({ detail: `Failed to fetch configuration, status: ${response.status}` }));
        console.error(`Error fetching configuration for ${interfaceName}:`, response.status, errorData.detail);
        message.error(`獲取配置失敗: ${errorData.detail || response.statusText || '未知錯誤'}`);
        const errorConfig = {
            interfaceName: interfaceName,
            apiKeys: [''], 
            modelName: defaultModelName, 
            prompt: null
        };
        setApiKeys(errorConfig.apiKeys);
        setSelectedModelName(errorConfig.modelName);
        setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: errorConfig }));
      }
    } catch (error) {
      console.error(`Network error or other issue fetching configuration for ${interfaceName}:`, error);
      message.error(`獲取配置時發生錯誤: ${error.message || '網絡錯誤'}`);
      const catchConfig = {
        interfaceName: interfaceName,
        apiKeys: [''], 
        modelName: defaultModelName, 
        prompt: null
      };
      setApiKeys(catchConfig.apiKeys);
      setSelectedModelName(catchConfig.modelName);
      setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: catchConfig }));
    }

    setIsModalOpen(true);
  };

  // Modal 確認按鈕的處理函數
  const handleOk = async () => {
    const validApiKeys = apiKeys.filter(key => key.trim() !== '');
    console.log('保存接口密鑰:', editingInterfaceName, validApiKeys);
    console.log('選中的模型名稱:', selectedModelName);

    const currentPrompt = interfaceConfigs[editingInterfaceName]?.prompt || null;

    const currentConfig = {
      interfaceName: editingInterfaceName,
      apiKeys: validApiKeys,
      modelName: selectedModelName,
      prompt: currentPrompt
    };

    try {
      const response = await fetch('http://localhost:8000/settings/model_setting', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(currentConfig),
      });

      if (response.ok) {
        const result = await response.json();
        message.success('接口配置保存成功！');
        setInterfaceConfigs(prev => ({ ...prev, [editingInterfaceName]: result.data_received || currentConfig }));
      } else {
        const errorData = await response.json().catch(() => ({ detail: '保存配置到後端失敗，且無法解析錯誤回應' }));
        console.error('保存配置到後端失敗:', response.status, errorData.detail || response.statusText);
        message.error(`保存配置失敗: ${errorData.detail || response.statusText || '未知錯誤'}`);
      }
    } catch (error) {
      console.error('調用後端 API 時發生網絡錯誤:', error);
      message.error(`保存配置時發生錯誤: ${error.message || '網絡錯誤'}`);
    }

    setIsModalOpen(false);
  };

  // Modal 取消按鈕的處理函數
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

  // 新增：處理打開「編輯參數」彈窗
  const handleEditParams = (interfaceName) => {
    setEditingParamsInterfaceName(interfaceName);
    const currentPrompt = interfaceConfigs[interfaceName]?.prompt || '';
    setPromptText(currentPrompt);
    setIsParamsModalOpen(true);
  };

  // 新增：「編輯參數」彈窗的確認按鈕處理函數
  const handleParamsOk = async () => {
    console.log(`保存接口 '${editingParamsInterfaceName}' 的提示詞:`, promptText);

    const existingConfig = interfaceConfigs[editingParamsInterfaceName]; 
    
    let currentApiKeys;
    let currentModelName;

    if (existingConfig) {
        currentApiKeys = existingConfig.apiKeys && existingConfig.apiKeys.length > 0 ? existingConfig.apiKeys : [''];
        currentModelName = existingConfig.modelName || modelNameOptions[editingParamsInterfaceName]?.[0]?.value;
    } else {
        if (editingInterfaceName === editingParamsInterfaceName) {
            currentApiKeys = apiKeys.filter(key => key.trim() !== '');
            if (currentApiKeys.length === 0) currentApiKeys = [''];
            currentModelName = selectedModelName || modelNameOptions[editingParamsInterfaceName]?.[0]?.value;
        } else {
            currentApiKeys = [''];
            currentModelName = modelNameOptions[editingParamsInterfaceName]?.[0]?.value;
        }
    }
    
    if (!currentModelName) {
      message.error(`無法確定接口 ${editingParamsInterfaceName} 的模型名稱，請先確保接口已在前端列表中定義或已編輯過其基本設置。`);
      setIsParamsModalOpen(false);
      return;
    }

    const payload = {
      interfaceName: editingParamsInterfaceName,
      apiKeys: currentApiKeys,
      modelName: currentModelName,
      prompt: promptText,
    };

    try {
      const response = await fetch('http://localhost:8000/settings/model_setting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (response.ok) {
        const result = await response.json();
        message.success('參數配置保存成功！');
        setInterfaceConfigs(prev => ({
          ...prev,
          [editingParamsInterfaceName]: result.data_received || payload 
        }));
      } else {
        const errorData = await response.json().catch(() => ({}));
        console.error('保存提示詞到後端失敗:', response.status, errorData.detail);
        message.error(`保存提示詞失敗: ${errorData.detail || response.statusText || '未知錯誤'}`);
      }
    } catch (error) {
      console.error('保存提示詞時發生網絡錯誤:', error);
      message.error(`保存提示詞時發生錯誤: ${error.message}`);
    }

    setIsParamsModalOpen(false);
  };

  // 「編輯參數」彈窗的取消按鈕處理函數
  const handleParamsCancel = () => {
    setIsParamsModalOpen(false);
  };

  // 處理測試接口邏輯
  const handleTestInterface = async (interfaceName) => {
    console.log(`準備測試接口: ${interfaceName}`);
    let config = interfaceConfigs[interfaceName];

    // 配置的緩存不存在，嘗試從後端加載
    if (!config) {
      try {
        console.log(`Fetching configuration for testing: ${interfaceName}`);
        const response = await fetch(`http://localhost:8000/settings/model_setting/${interfaceName}`);
        if (response.ok) {
          const data = await response.json();
          if (data) {
            setInterfaceConfigs(prev => ({ ...prev, [interfaceName]: data }));
            config = data;
          } else {
            message.warning({ content: `${interfaceName} 接口尚未配置，請先編輯接口。`, key: `fetchConfig-${interfaceName}`, duration: 3 });
            return;
          }
        } else {
          const errorData = await response.json().catch(() => ({ detail: `Failed to fetch configuration, status: ${response.status}` }));
          message.error({ content: `獲取 ${interfaceName} 配置失敗: ${errorData.detail || response.statusText || '請先編輯接口並保存'}`, key: `fetchConfig-${interfaceName}`, duration: 3 });
          return;
        }
      } catch (error) {
        console.error(`Network error or other issue fetching configuration for ${interfaceName} during test:`, error);
        message.error({ content: `獲取 ${interfaceName} 配置時發生錯誤: ${error.message || '網絡錯誤'}`, key: `fetchConfig-${interfaceName}`, duration: 3 });
        return;
      }
    }

    if (!config || !config.apiKeys || config.apiKeys.length === 0) {
      message.warning(`請先為 ${interfaceName} 接口配置並保存至少一個 API Key。`);
      handleEditInterface(interfaceName);
      return;
    }

    const apiKeysToTest = config.apiKeys.filter(key => key && key.trim() !== '');
    if (apiKeysToTest.length === 0) {
        message.warning(`請先為 ${interfaceName} 接口配置並保存有效的 API Key。`);
        return;
    }

    message.loading({ content: `正在測試 ${interfaceName} 接口...`, key: 'testInterface' });

    try {
      const response = await fetch('http://localhost:8000/settings/test_model_interface', { // 假設的後端端點
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          interfaceName: interfaceName,
          apiKeys: apiKeysToTest,
        }),
      });

      const result = await response.json();

      if (response.ok) {
        console.log(`接口 ${interfaceName} 測試成功:`, result);
        message.success({ content: `${interfaceName} 接口測試成功: ${result.message || '所有密鑰均有效'}`, key: 'testInterface', duration: 3 });
        if (result.details) {
            console.log('測試詳情:', result.details);
        }
      } else {
        console.error(`接口 ${interfaceName} 測試失敗:`, result);
        message.error({ content: `${interfaceName} 接口測試失敗: ${result.detail || result.message || '未知錯誤'}`, key: 'testInterface', duration: 5 });
      }
    } catch (error) {
      console.error(`測試接口 ${interfaceName} 時發生網絡錯誤:`, error);
      message.error({ content: `測試 ${interfaceName} 接口時發生錯誤: ${error.message || '網絡問題'}`, key: 'testInterface', duration: 5 });
    }
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
            {/* 使用 Space 組件包裹三個固定的 Dropdown 按鈕 */}
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
        
        <div style={{ marginBottom: '16px' }}>
          <div style={{ marginBottom: '8px', fontWeight: 500 }}>模型名稱</div>
          <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: '12px', marginBottom: '8px' }}>
            請選擇或者輸入要使用的模型的名稱。
          </div>
          <Select
            style={{ width: '100%' }}
            placeholder="請選擇模型名稱"
            value={selectedModelName}
            onChange={(value) => setSelectedModelName(value)}
            showSearch
            optionFilterProp="children"
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          >
            {getCurrentModelOptions().map(option => (
              <Option key={option.value} value={option.value} label={option.label}>
                {option.label}
              </Option>
            ))}
          </Select>
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
    </div>
  );
};

export default ModelManager;