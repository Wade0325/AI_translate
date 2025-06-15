import React, { useState } from 'react';
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
import axios from 'axios';

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

// --- 後端 API 通訊 ---
const API_BASE_URL = 'http://localhost:8000/api/v1';

const transcribeFile = async (file, sourceLang, targetLang, model) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source_lang', sourceLang);
  formData.append('target_lang', targetLang);
  formData.append('model', model);

  try {
    const response = await axios.post(`${API_BASE_URL}/transcribe`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
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


// --- 主要應用程式元件 ---
const Transcription = () => {
  const [fileList, setFileList] = useState([]);
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [outputFormats, setOutputFormats] = useState(['srt']);
  const [model, setModel] = useState('Google');
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
        filesToProcess.find(p => p.uid === file.uid)
          ? { ...file, status: 'processing' }
          : file
      )
    );

    const uploadPromises = filesToProcess.map(async (file) => {
      try {
        const response = await transcribeFile(
          file.originFileObj,
          sourceLang,
          targetLang,
          model
        );
        
        console.log('API Response:', response);

        // 將回傳的純文字稿，根據使用者選擇的格式，建立一個結果物件
        // 注意：目前後端只回傳純文字，所以對於 SRT/VTT 等格式，內容是相同的。
        // 未來若後端支援時間戳，此處邏輯需要擴充。
        const resultObject = {};
        outputFormats.forEach(format => {
          resultObject[format] = response.transcribed_text;
        });

        setFileList(currentList => {
          const newList = currentList.map(f => {
            if (f.uid === file.uid) {
              return {
                ...f,
                status: 'completed',
                result: resultObject,
                formats: outputFormats,
              };
            } else {
              return f;
            }
          });
          return newList;
        });
        return { status: 'fulfilled', uid: file.uid };
      } catch (error) {
        console.error(`檔案 ${file.name} 上傳失敗:`, error);
        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'error' } : f
          )
        );
        return { status: 'rejected', uid: file.uid, error };
      }
    });

    await Promise.allSettled(uploadPromises);

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
            <Col xs={24} sm={12} md={6}>
              <Text>選擇服務商</Text>
              <Select value={model} style={{ width: '100%' }} onChange={setModel}>
                {modelOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
              </Select>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Text>來源語言</Text>
              <Select value={sourceLang} style={{ width: '100%' }} onChange={setSourceLang}>
                {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
              </Select>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Text>輸出語言</Text>
              <Select value={targetLang} style={{ width: '100%' }} onChange={setTargetLang}>
                {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
              </Select>
            </Col>
            <Col xs={24} sm={12} md={6}>
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

  return <TranscriptionPage />;
};

export default Transcription;