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
  Modal,
  Input,
  message,
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
  EyeOutlined,
} from '@ant-design/icons';
import { useTranscription } from '../context/TranscriptionContext';
import { useModelManager } from './ModelManager';
// 引入統一的設定和輔助函數
import { modelNameOptions, findProviderForModel, isModelValid } from '../constants/modelConfig';

const { Title, Text } = Typography;
const { Option } = Select;

// --- 語言和格式選項 ---
const languageOptions = [
  { value: 'zh-TW', label: '繁體中文 (台灣)' },
  { value: 'en-US', label: '英文 (美國)' },
];

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

  // YT 連結輸入框狀態
  const [youtubeUrl, setYoutubeUrl] = useState('');

  // 預覽 Modal 狀態
  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [previewContent, setPreviewContent] = useState('');
  const [previewTitle, setPreviewTitle] = useState('');

  // 新增狀態來管理當前選擇的服務商
  const [selectedProvider, setSelectedProvider] = useState(() => findProviderForModel(model));

  // 當全局 model 狀態變化時，同步更新服務商
  useEffect(() => {
    const provider = findProviderForModel(model);
    setSelectedProvider(provider);
  }, [model]);

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

  // YT 連結加入佇列處理函式
  const handleAddYoutubeUrl = () => {
    if (!youtubeUrl.trim()) {
      message.warning('請輸入 YouTube 連結');
      return;
    }
    // 簡易 YouTube 連結格式驗證
    const ytRegex = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+$/;
    if (!ytRegex.test(youtubeUrl)) {
      message.error('請輸入有效的 YouTube 連結');
      return;
    }

    const newFile = {
      uid: `yt-${Date.now()}`,
      name: youtubeUrl,
      status: 'waiting',
      percent: 0,
      size: 0, // 設為 0 以避免表格顯示錯誤
      originFileObj: null, // 非實際檔案，設為 null
    };

    setFileList(list => [...list, newFile]);
    setYoutubeUrl(''); // 清空輸入框
    message.success('已成功將 YouTube 連結加入佇列');
  };

  // Modal 處理函式
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
      width: '10%',
      render: (size) => `${(size / 1024 / 1024).toFixed(2)} MB` 
    },
    {
      title: 'Tokens',
      dataIndex: 'tokens_used',
      key: 'tokens_used',
      width: '10%',
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
      width: '10%',
      render: (cost, record) => (record.status === 'completed' && cost ? `$${cost.toFixed(4)}` : '-'),
    },
    {
      title: '進度',
      dataIndex: 'status',
      key: 'status',
      width: '10%',
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
      width: '25%',
      render: (_, record) => {
        const availableFormats = ['lrc', 'srt', 'vtt', 'txt'];
        return (
          <Space>
            {record.status === 'completed' && record.result?.txt && (
              <Tooltip title="預覽內容">
                <Button
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => handleOpenPreview(record)}
                />
              </Tooltip>
            )}
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
      <Row gutter={32} justify="end" style={{ marginTop: '16px', paddingRight: '8px' }}>
        <Col>
          <Statistic title={<span style={{fontSize: '14px', color: 'rgba(0, 0, 0, 0.45)'}}>完成檔案</span>} value={completedFilesCount} valueStyle={{fontSize: '20px'}} prefix={<CheckCircleOutlined />} />
        </Col>
        <Col>
          <Statistic title={<span style={{fontSize: '14px', color: 'rgba(0, 0, 0, 0.45)'}}>總消耗 Tokens</span>} value={totalTokens} valueStyle={{fontSize: '20px'}} prefix={<DashboardOutlined />} />
        </Col>
        <Col>
          <Statistic title={<span style={{fontSize: '14px', color: 'rgba(0, 0, 0, 0.45)'}}>預估總花費 (USD)</span>} value={totalCost} precision={4} valueStyle={{fontSize: '20px'}} prefix={<DollarCircleOutlined />} />
        </Col>
      </Row>
    </div>
  );

  const completedFilesCount = fileList.filter(f => f.status === 'completed').length;
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
          <Divider></Divider>
          <Row gutter={8}>
            <Col flex="auto">
              <Input
                placeholder="貼上 YouTube 影片連結以加入轉錄佇列"
                value={youtubeUrl}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                onPressEnter={handleAddYoutubeUrl}
              />
            </Col>
            <Col>
              <Button type="primary" onClick={handleAddYoutubeUrl}>加入佇列</Button>
            </Col>
          </Row>
      </Card>

      <Card title="2. 轉錄設定">
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
              {modelNameOptions[selectedProvider]?.map(option => (
                  <Option key={option.value} value={option.value}>{option.label}</Option>
              ))}
            </Select>
          </Col>
          {/* <Col xs={24} sm={8}>
            <Text>來源語言</Text>
            <Select value={sourceLang} style={{ width: '100%' }} onChange={setSourceLang}>
              {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
            </Select>
          </Col> */}
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: '8px' }}>
          <Col xs={24} sm={8}>
            <Space.Compact style={{ width: '100%' }}>
              <Tooltip title="編輯API金鑰與模型" placement="bottom">
                <Button
                  icon={<EditOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleEditInterface(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  編輯API
                </Button>
              </Tooltip>
              {/* <Tooltip title="編輯 Prompt 參數" placement="bottom">
                <Button
                  icon={<SlidersOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleEditParams(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  編輯參數
                </Button>
              </Tooltip> */}
              <Tooltip title="測試此API是否可用" placement="bottom">
                <Button
                  icon={<PlayCircleOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleTestInterface(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  測試API
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

      <Modal
        title={previewTitle}
        open={isPreviewModalVisible}
        onCancel={handleClosePreview}
        footer={null}
        width="60vw"
      >
        <div style={{ maxHeight: '60vh', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
          {previewContent}
        </div>
      </Modal>
    </Space>
  );
};

export default Transcription;