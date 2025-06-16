import React from 'react';
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
} from '@ant-design/icons';
import { useTranscription } from '../context/TranscriptionContext'; // 引入 hook

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

const formatOptions = [
  { value: 'srt', label: 'SRT (.srt)' },
  { value: 'vtt', label: 'WebVTT (.vtt)' },
  { value: 'lrc', label: 'LRC (.lrc)' },
  { value: 'txt', label: '純文字 (.txt)' },
];

const modelOptions = [
    { value: 'Google', label: 'Google' }
]

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
  } = useTranscription();

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
      width: '45%',
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
      width: '15%',
      render: (size) => `${(size / 1024 / 1024).toFixed(2)} MB` 
    },
    {
      title: '狀態',
      dataIndex: 'status',
      key: 'status',
      width: '20%',
      render: (status) => {
        const statusMap = {
          waiting: { color: 'default', text: '等待中' },
          processing: { color: 'processing', text: '處理中', icon: <SyncOutlined spin /> },
          completed: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
          error: { color: 'error', text: '失敗', icon: <CloseCircleOutlined /> },
        };
        const { color, text, icon } = statusMap[status] || statusMap.waiting;
        return <Tag icon={icon} color={color}>{text}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: '20%',
      render: (_, record) => {
        const availableFormats = ['lrc', 'srt', 'vtt', 'txt'];
        return (
          <Space>
            {record.status === 'completed' && record.result && availableFormats.map(format => (
              <Tooltip title={`下載 ${format.toUpperCase()}`} key={format}>
                <Button
                  size="small"
                  onClick={() => downloadFile(record.result[format], record.name, format)}
                >
                  {format.toUpperCase()}
                </Button>
              </Tooltip>
            ))}
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
              <Upload {...uploadProps}>
                  <Button icon={<PlusOutlined />}>新增檔案</Button>
              </Upload>
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
        <Row gutter={[16, 16]} align="top">
          <Col xs={24} sm={12} md={12}>
            <Text>選擇服務商</Text>
            <Select value={model} style={{ width: '100%' }} onChange={setModel}>
              {modelOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
            </Select>
          </Col>
          <Col xs={24} sm={12} md={12}>
            <Text>來源語言</Text>
            <Select value={sourceLang} style={{ width: '100%' }} onChange={setSourceLang}>
              {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
            </Select>
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