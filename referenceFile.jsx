import React, { useState } from 'react';
import {
  Layout,
  Upload,
  Button,
  Select,
  Table,
  Typography,
  Space,
  Row,
  Col,
  Card,
  message,
  Tag,
  Tooltip,
} from 'antd';
import {
  UploadOutlined,
  AudioOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';

// 從 Ant Design 引入所需元件
const { Content } = Layout;
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

// --- 模擬後端處理 ---
const simulateTranscription = (file, sourceLang, targetLang) => {
  console.log(`開始轉錄: ${file.name}, 來源語言: ${sourceLang}, 目標語言: ${targetLang}`);
  return new Promise(resolve => {
    const delay = Math.random() * 3000 + 2000;
    setTimeout(() => {
      const mockText = `這是"${file.name}"的模擬轉錄結果。\n來源語言是 ${sourceLang}，目標語言是 ${targetLang}。\n這是一段示範文字，用於生成不同格式的字幕檔案。`;
      console.log(`完成轉錄: ${file.name}`);
      resolve(mockText);
    }, delay);
  });
};

const generateSubtitleContent = (format, text) => {
  const lines = text.split('\n');
  switch (format) {
    case 'srt':
      return lines.map((line, index) => 
        `${index + 1}\n00:00:0${index * 2}.000 --> 00:00:0${index * 2 + 1}.500\n${line}\n`
      ).join('\n');
    case 'vtt':
      return 'WEBVTT\n\n' + lines.map((line, index) => 
        `00:00:0${index * 2}.000 --> 00:00:0${index * 2 + 1}.500\n${line}\n`
      ).join('\n');
    case 'lrc':
      return lines.map((line, index) => `[00:0${index * 2}.00]${line}`).join('\n');
    default:
      return text;
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


// --- 主要應用程式元件 ---
const App = () => {
  const [fileList, setFileList] = useState([]);
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [outputFormats, setOutputFormats] = useState(['srt']);
  const [isProcessing, setIsProcessing] = useState(false);

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
        filesToProcess.some(p => p.uid === file.uid)
          ? { ...file, status: 'processing' }
          : file
      )
    );

    for (const file of filesToProcess) {
      try {
        const transcribedText = await simulateTranscription(file.originFileObj, sourceLang, targetLang);
        
        const results = {};
        for (const format of outputFormats) {
          results[format] = generateSubtitleContent(format, transcribedText);
        }
        
        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'completed', result: results, formats: outputFormats } : f
          )
        );
        
      } catch (error) {
        console.error('轉錄失敗:', error);
        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'error' } : f
          )
        );
      }
    }

    setIsProcessing(false);
    message.success('所有新任務處理完畢！');
  };

  const handleFormatChange = (newValue) => {
    if (newValue.length === 0) {
      message.warning('至少需要選擇一種輸出格式。');
      return;
    }
    setOutputFormats(newValue);
  };

  // --- 轉錄頁面元件 ---
  const TranscriptionPage = () => {
    const uploadProps = {
      multiple: true,
      fileList,
      onChange: handleUploadChange,
      beforeUpload: () => false,
      showUploadList: false,
    };
    
    const fileListColumns = [
      { 
        title: '檔案名稱', 
        dataIndex: 'name', 
        key: 'name', 
        width: '45%',
        render: (name) => (
          <Tooltip title={name} overlayStyle={{ maxWidth: '600px' }}>
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
        render: (_, record) => (
          <Space>
            {record.status === 'completed' && record.formats?.map(format => (
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
        ),
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

    return (
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Card title="1. 上傳與管理檔案">
            {fileList.length === 0 ? <UploadArea /> : <FileListArea />}
        </Card>

        <Card title="2. 轉錄設定">
          <Row gutter={[16, 16]} align="top">
            <Col xs={24} sm={12} md={8}>
              <Text>來源語言</Text>
              <Select value={sourceLang} style={{ width: '100%' }} onChange={setSourceLang}>
                {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
              </Select>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Text>輸出語言</Text>
              <Select value={targetLang} style={{ width: '100%' }} onChange={setTargetLang}>
                {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
              </Select>
            </Col>
            <Col xs={24} sm={24} md={8}>
              <Text>輸出格式</Text>
              <Select
                mode="multiple"
                value={outputFormats}
                style={{ width: '100%' }}
                placeholder="請選擇輸出格式"
                onChange={handleFormatChange}
              >
                {formatOptions.map(fmt => <Option key={fmt.value} value={fmt.value}>{fmt.label}</Option>)}
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
      </Space>
    );
  };

  return (
    <Layout style={{ minHeight: '100vh', background: '#f0f2f5' }}>
      <style>{`
        html {
          overflow-y: scroll;
        }
      `}</style>
      <Content style={{ padding: '24px 50px' }}>
          <TranscriptionPage />
      </Content>
    </Layout>
  );
};

export default App;
