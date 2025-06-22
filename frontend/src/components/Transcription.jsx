import React, { useState, useEffect } from 'react';
import {
  Upload,
  Button,
  Select,
  Table,
  Typography,
  Space,
  Row,
  Col,
  Card,
  Tag,
  Tooltip,
  Statistic,
  Progress,
  Popconfirm,
  Divider,
} from 'antd';
import {
  UploadOutlined,
  AudioOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlusOutlined,
  DashboardOutlined,
  DollarCircleOutlined,
  InfoCircleOutlined,
  DeleteOutlined,
  ReloadOutlined,
  EditOutlined,
  SlidersOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { useTranscription } from '../context/TranscriptionContext'; // 引入 hook
import { useModelManager } from './ModelManager'; // 引入新的 hook

const { Title, Text } = Typography;
const { Option } = Select;

// --- 語言和格式選項 ---
const languageOptions = [
  { value: 'zh-TW', label: '繁體中文 (台灣)' },
  { value: 'zh-CN', label: '簡體中文 (中國)' },
  { value: 'en-US', label: '英文 (美國)' },
  { value: 'ja-JP', label: '日文' },
  { value: 'ko-KR', label: '韓文' },
  { value: 'es-ES', label: '西班牙文' },
];

// 建立一個包含所有服務商及其模型的完整物件
const modelNameOptions = {
  Google: [
    { value: 'gemini-1.5-pro-latest', label: 'gemini-1.5-pro-latest' },
    { value: 'gemini-1.5-flash-latest', label: 'gemini-1.5-flash-latest' },
  ],
  OpenAI: [
    { value: 'gpt-4-turbo', label: 'gpt-4-turbo' },
    { value: 'gpt-4o', label: 'gpt-4o' },
    { value: 'gpt-3.5-turbo', label: 'gpt-3.5-turbo' },
  ],
  Claude: [
    { value: 'claude-3-opus-20240229', label: 'claude-3-opus-20240229' },
    { value: 'claude-3-sonnet-20240229', label: 'claude-3-sonnet-20240229' },
    { value: 'claude-3-haiku-20240307', label: 'claude-3-haiku-20240307'},
  ],
  SakuraLLM: [
    { value: 'Sakura-v0.8-Llama-3-8B-MLM', label: 'Sakura-v0.8-Llama-3-8B-MLM' },
  ]
};

// 輔助函式：根據模型名稱尋找其服務商
const findProviderForModel = (modelName) => {
  if (!modelName) return null;
  for (const provider in modelNameOptions) {
    if (modelNameOptions[provider].some(option => option.value === modelName)) {
      return provider;
    }
  }
  return 'Google'; // 預設返回 Google
};

// 新增：检查模型名称是否有效
const isModelValid = (modelName) => {
  if (!modelName) return false;
  for (const provider in modelNameOptions) {
    if (modelNameOptions[provider].some(option => option.value === modelName)) {
      return true;
    }
  }
  return false;
};

// --- 主要應用程式元件 ---
const Transcription = () => {
  // 從 Context 取用所有需要的狀態和函式
  const {
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
  } = useTranscription();
  
  // 從 ModelManager Context 獲取函式
  const { handleEditInterface, handleEditParams, handleTestInterface } = useModelManager();

  // 新增狀態來管理當前選擇的服務商
  const [selectedProvider, setSelectedProvider] = useState(() => findProviderForModel(model));

  // 當全局 model 狀態變化時，同步更新服務商
  useEffect(() => {
    const provider = findProviderForModel(model);
    setSelectedProvider(provider);
  }, [model]);

  // 改进：在元件首次加載时检查并设定预设模型
  useEffect(() => {
    // 如果 model 的值不是一个有效的模型名称，则设定一个预设值
    if (!isModelValid(model)) {
      const defaultProvider = 'Google'; // 預設服務商
      const defaultModel = modelNameOptions[defaultProvider]?.[0]?.value;
      if (defaultModel) {
        setModel(defaultModel);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // 空依賴陣列確保此效果只在初始渲染時執行一次

  // 處理服務商變更的事件
  const handleProviderChange = (newProvider) => {
    setSelectedProvider(newProvider);
    // 當服務商變更時，自動選擇該服務商的第一個模型
    const defaultModel = modelNameOptions[newProvider]?.[0]?.value;
    if (defaultModel) {
      setModel(defaultModel);
    } else {
      setModel(null); // 如果該服務商沒有模型，則清空
    }
  };

  // --- 轉錄頁面元件 ---
  const uploadProps = {
    multiple: true,
    fileList,
    onChange: handleUploadChange,
    beforeUpload: () => false,
    showUploadList: false,
    accept: 'audio/*',
  };
  
  const fileListColumns = [
    { 
      title: '檔案名稱', 
      dataIndex: 'name', 
      key: 'name', 
      width: '33%',
      render: (name) => (
        <Tooltip title={name} popupStyle={{ maxWidth: '600px' }}>
          <span style={{
            display: 'block',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {name}
          </span>
        </Tooltip>
      ),
    },
    { 
      title: '大小', 
      dataIndex: 'size', 
      key: 'size', 
      width: '12%',
      render: (size) => `${(size / 1024 / 1024).toFixed(2)} MB` 
    },
    {
      title: 'Tokens',
      dataIndex: 'tokens_used',
      key: 'tokens_used',
      width: '12%',
      render: (tokens) => (tokens ? tokens.toLocaleString() : '-'),
    },
    {
      title: (
        <Space size="small">
          <span>金額 (USD)</span>
          <Tooltip title="此為預估值，點擊圖示查看 Gemini API 官方計價。">
            <a href="https://ai.google.dev/pricing" target="_blank" rel="noopener noreferrer">
              <InfoCircleOutlined style={{ color: 'rgba(0,0,0,.45)', cursor: 'pointer', fontSize: '12px' }} />
            </a>
          </Tooltip>
        </Space>
      ),
      dataIndex: 'cost',
      key: 'cost',
      width: '13%',
      render: (cost, record) => (record.status === 'completed' && cost ? `$${cost.toFixed(4)}` : '-'),
    },
    {
      title: '進度',
      dataIndex: 'status',
      key: 'status',
      width: '15%',
      render: (status, record) => {
        let progressStatus;
        if (status === 'completed') progressStatus = 'success';
        else if (status === 'error') progressStatus = 'exception';
        else if (status === 'processing') progressStatus = 'active';
        else progressStatus = 'normal';
        
        return <Progress percent={record.percent} status={progressStatus} size="small" />;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: '15%',
      render: (_, record) => {
        const availableFormats = ['lrc', 'srt', 'vtt', 'txt'];
        return (
          <Space>
            {record.status === 'completed' && record.result && availableFormats.map(format => (
              <Tooltip title={`下載 ${format.toUpperCase()}`} key={format}>
                <Button
                  size="small"
                  onClick={() => downloadFile(record.result[format], record.name, format)}
                  disabled={!record.result[format]}
                >
                  {format.toUpperCase()}
                </Button>
              </Tooltip>
            ))}
            {(record.status === 'completed' || record.status === 'error') && (
              <Tooltip title="重新處理">
                <Popconfirm
                  title="確定要重新處理此任務嗎?"
                  onConfirm={() => handleReprocess(record.uid)}
                  okText="確定"
                  cancelText="取消"
                >
                  <Button size="small" icon={<ReloadOutlined />} />
                </Popconfirm>
              </Tooltip>
            )}
             <Tooltip title="移除">
               <Button
                  size="small"
                  danger
                  icon={<CloseCircleOutlined />}
                  onClick={() => setFileList(list => list.filter(f => f.uid !== record.uid))}
              />
             </Tooltip>
          </Space>
        );
      }
    },
  ];

  const UploadArea = () => (
    <Upload.Dragger {...uploadProps} height={200}>
      <p className="ant-upload-drag-icon">
        <UploadOutlined />
      </p>
      <p className="ant-upload-text">點擊或拖曳多個音訊/視訊檔案到此區域</p>
      <p className="ant-upload-hint">支援單次或批次上傳，上傳後列表將會取代此處。</p>
    </Upload.Dragger>
  );

  const FileListArea = () => (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col>
              <Title level={5} style={{ margin: 0 }}>本次任務佇列</Title>
          </Col>
          <Col>
            <Space>
              <Upload {...uploadProps}>
                  <Button icon={<PlusOutlined />}>新增檔案</Button>
              </Upload>
              {fileList.length > 0 && (
                <Popconfirm
                  title="確定要清除所有任務嗎？"
                  onConfirm={clearAllFiles}
                  okText="確定"
                  cancelText="取消"
                  placement="bottomRight"
                >
                  <Button danger icon={<DeleteOutlined />}>全部清除</Button>
                </Popconfirm>
              )}
            </Space>
          </Col>
      </Row>
      <Table
        size="small"
        columns={fileListColumns}
        dataSource={fileList}
        rowKey="uid"
        pagination={{ pageSize: 5 }}
        tableLayout="fixed"
      />
    </div>
  );

  const totalTokens = fileList
    .filter(f => f.status === 'completed')
    .reduce((acc, file) => acc + (file.tokens_used || 0), 0);
  const totalCost = fileList
    .filter(f => f.status === 'completed')
    .reduce((acc, file) => acc + (file.cost || 0), 0);

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card title="1. 上傳與管理檔案">
          {fileList.length === 0 ? <UploadArea /> : <FileListArea />}
      </Card>

      <Card title="2. 轉錄設定">
        {/* 第一行：三個下拉選單，確保水平對齊 */}
        <Row gutter={[16, 16]} align="bottom">
          <Col xs={24} sm={8}>
            <Text>選擇服務商</Text>
            <Select
              value={selectedProvider}
              style={{ width: '100%' }}
              onChange={handleProviderChange}
            >
              {Object.keys(modelNameOptions).map(provider => (
                <Option key={provider} value={provider}>{provider}</Option>
              ))}
            </Select>
          </Col>
          <Col xs={24} sm={8}>
            <Text>選擇模型</Text>
            <Select
              value={model}
              style={{ width: '100%' }}
              onChange={setModel}
              disabled={!selectedProvider}
            >
              {selectedProvider && modelNameOptions[selectedProvider] ? (
                modelNameOptions[selectedProvider].map(option => (
                  <Option key={option.value} value={option.value}>{option.label}</Option>
                ))
              ) : (
                <Option value={null} disabled>請先選擇服務商</Option>
              )}
            </Select>
          </Col>
          <Col xs={24} sm={8}>
            <Text>來源語言</Text>
            <Select value={sourceLang} style={{ width: '100%' }} onChange={setSourceLang}>
              {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
            </Select>
          </Col>
        </Row>
        
        {/* 第二行：只在第一欄下方顯示按鈕 */}
        <Row gutter={[16, 16]} style={{ marginTop: '8px' }}>
          <Col xs={24} sm={8}>
            <Space.Compact style={{ width: '100%' }}>
              <Tooltip title="編輯接口金鑰與模型">
                <Button
                  icon={<EditOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleEditInterface(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  編輯接口
                </Button>
              </Tooltip>
              <Tooltip title="編輯 Prompt 參數">
                <Button
                  icon={<SlidersOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleEditParams(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  編輯參數
                </Button>
              </Tooltip>
              <Tooltip title="測試此接口是否可用">
                <Button
                  icon={<PlayCircleOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleTestInterface(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  測試接口
                </Button>
              </Tooltip>
            </Space.Compact>
          </Col>
        </Row>
      </Card>
      
      <Card title="3. 開始轉錄">
        <Button
          type="primary"
          icon={<AudioOutlined />}
          size="large"
          loading={isProcessing}
          onClick={handleStartTranscription}
          style={{ width: '100%' }}
          disabled={fileList.filter(f => f.status === 'waiting').length === 0}
        >
          {isProcessing ? '正在處理中...' : `開始轉錄 (${fileList.filter(f => f.status === 'waiting').length} 個新檔案)`}
        </Button>
      </Card>

      <Card title="4. 任務摘要">
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12}>
            <Statistic title="總消耗 Tokens" value={totalTokens} prefix={<DashboardOutlined />} />
          </Col>
          <Col xs={24} sm={12}>
            <Statistic title="預估總花費 (USD)" value={totalCost} precision={4} prefix={<DollarCircleOutlined />} />
          </Col>
        </Row>
      </Card>
    </Space>
  );
};

export default Transcription;