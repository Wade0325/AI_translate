import React, { useState, useEffect } from 'react';
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
  Statistic,
  Popconfirm,
  Progress,
  ConfigProvider,
  theme as antdTheme,
  Switch,
} from 'antd';
import {
  UploadOutlined,
  AudioOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlusOutlined,
  DollarCircleOutlined,
  InfoCircleOutlined,
  DeleteOutlined,
  MoonOutlined,
  SunOutlined,
  ReloadOutlined,
} from '@ant-design/icons';

// 從 Ant Design 引入所需元件
const { Content, Header } = Layout;
const { Title, Text } = Typography;
const { Option } = Select;
const { useToken } = antdTheme;

// --- 語言和格式選項 ---
const languageOptions = [
  { value: 'zh-TW', label: '繁體中文 (台灣)' },
  { value: 'en-US', label: '英文 (美國)' },
];

// 假設的計價模型
const TOKEN_PRICE_PER_THOUSAND = 0.002; // 每 1000 tokens 的價格

// --- 模擬後端處理 ---
const simulateTranscription = (file, sourceLang, targetLang, onProgress) => {
  console.log(`開始轉錄: ${file.name}, 來源語言: ${sourceLang}, 目標語言: ${targetLang}`);
  return new Promise((resolve, reject) => {
    const delay = Math.random() * 2000 + 1000; // 1-3 秒
    const intervals = 5;
    let currentProgress = 0;

    const intervalId = setInterval(() => {
        currentProgress += 100 / intervals;
        if(currentProgress <= 100) {
            onProgress(Math.min(currentProgress, 100));
        }
    }, delay / intervals);

    setTimeout(() => {
        clearInterval(intervalId);
         if (Math.random() > 0.1) { // 90% 成功率
            const mockText = `這是"${file.name}"的模擬轉錄結果。\n來源語言是 ${sourceLang}，目標語言是 ${targetLang}。\n這是一段示範文字，用於生成不同格式的字幕檔案。`;
            const mockTokens = Math.floor(Math.random() * 14000) + 1000;
            console.log(`完成轉錄: ${file.name}, 使用了 ${mockTokens} tokens`);
            resolve({ text: mockText, tokens: mockTokens });
        } else { // 10% 失敗率
            console.error(`轉錄失敗: ${file.name}`);
            reject(new Error("模擬轉錄失敗"));
        }
    }, delay + 200);
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

// --- 轉錄頁面內容元件 ---
const TranscriptionPage = () => {
  const [fileList, setFileList] = useState([]);
  const [sourceLang, setSourceLang] = useState('zh-TW');
  const [targetLang, setTargetLang] = useState('zh-TW');
  const [outputFormats, setOutputFormats] = useState(['srt']);
  const [isProcessing, setIsProcessing] = useState(false);
  const [summary, setSummary] = useState({ count: 0, totalTokens: 0, totalCost: 0 });
    
  useEffect(() => {
      const processedFiles = fileList.filter(f => f.status === 'completed');
      const totalTokens = processedFiles.reduce((acc, file) => acc + (file.tokens || 0), 0);
      const totalCost = processedFiles.reduce((acc, file) => acc + (file.cost || 0), 0);
      setSummary({
          count: processedFiles.length,
          totalTokens: totalTokens,
          totalCost: totalCost
      });
  }, [fileList]);

  const handleUploadChange = ({ fileList: newFileList }) => {
    const updatedList = newFileList.map(f => ({
      ...f,
      status: f.status || 'waiting',
      tokens: 0,
      cost: 0,
      percent: 0,
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

    for (const file of filesToProcess) {
       setFileList(currentList =>
            currentList.map(f =>
                f.uid === file.uid ? { ...f, status: 'processing', percent: 0 } : f
            )
        );

      try {
        const onProgress = (percent) => {
            setFileList(currentList =>
                currentList.map(f =>
                    f.uid === file.uid ? { ...f, percent } : f
                )
            );
        };

        const transcribedData = await simulateTranscription(file.originFileObj, sourceLang, targetLang, onProgress);
        
        const results = {};
        for (const format of outputFormats) {
          results[format] = generateSubtitleContent(format, transcribedData.text);
        }
        
        const cost = (transcribedData.tokens / 1000) * TOKEN_PRICE_PER_THOUSAND;

        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid ? { 
              ...f, 
              status: 'completed', 
              result: results, 
              formats: outputFormats,
              tokens: transcribedData.tokens,
              cost: cost,
              percent: 100,
            } : f
          )
        );
        
      } catch (error) {
        console.error('轉錄失敗:', error);
        setFileList(currentList =>
          currentList.map(f =>
            f.uid === file.uid ? { ...f, status: 'error', percent: 100 } : f
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

  const handleReprocess = (uidToReprocess) => {
    setFileList(currentList => currentList.map(file => {
        if(file.uid === uidToReprocess) {
            return {
                ...file,
                status: 'waiting',
                percent: 0,
                tokens: 0,
                cost: 0,
                result: null,
                formats: [],
            };
        }
        return file;
    }));
    message.info(`任務 "${fileList.find(f => f.uid === uidToReprocess)?.name}" 已重新加入佇列。`);
  };

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
      width: '33%',
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
      width: '12%',
      render: (size) => `${(size / 1024 / 1024).toFixed(2)} MB` 
    },
    {
      title: 'Tokens',
      dataIndex: 'tokens',
      key: 'tokens',
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
      render: (cost) => (cost ? `$${cost.toFixed(4)}` : '-'),
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

  const FileListArea = () => {
    const handleClearAll = () => {
      setFileList([]);
      message.success("已清除所有任務");
    };

    return (
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
                        onConfirm={handleClearAll}
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
  };

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

      <Card title="本次任務摘要">
          <Row gutter={16}>
              <Col span={8}>
                  <Statistic title="已處理檔案數" value={summary.count} />
              </Col>
              <Col span={8}>
                  <Statistic title="總 Tokens 使用量" value={summary.totalTokens.toLocaleString()} />
              </Col>
              <Col span={8}>
                  <Statistic 
                      title={
                          <Space>
                              <span>預估總花費 (USD)</span>
                              <Tooltip title="此為預估值，點擊圖示查看 Gemini API 官方計價。">
                                  <a href="https://ai.google.dev/pricing" target="_blank" rel="noopener noreferrer">
                                      <InfoCircleOutlined style={{ color: 'rgba(0,0,0,.45)', cursor: 'pointer' }} />
                                  </a>
                              </Tooltip>
                          </Space>
                      }
                      value={summary.totalCost} 
                      precision={4} 
                      prefix={<DollarCircleOutlined />} 
                  />
              </Col>
          </Row>
      </Card>
    </Space>
  );
};

// --- App 內容封裝元件 ---
const AppContent = ({ theme, setTheme }) => {
    const { token } = useToken();
    return (
        <Layout style={{ minHeight: '100vh', backgroundColor: token.colorBgLayout }}>
            <style>{`
                html {
                overflow-y: scroll;
                }
            `}</style>
            <Header style={{ 
                backgroundColor: token.colorBgContainer, 
                borderBottom: `1px solid ${token.colorBorderSecondary}`,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                position: 'sticky',
                top: 0,
                zIndex: 10,
            }}>
                <Title level={4} style={{ margin: 0, color: token.colorText }}>語音轉錄工具</Title>
                <Switch
                    checkedChildren={<SunOutlined />}
                    unCheckedChildren={<MoonOutlined />}
                    checked={theme === 'light'}
                    onChange={(checked) => setTheme(checked ? 'light' : 'dark')}
                />
            </Header>
            <Content style={{ padding: '24px 50px' }}>
                <TranscriptionPage />
            </Content>
        </Layout>
    );
};


// --- 主應用程式元件 ---
const App = () => {
    const [theme, setTheme] = useState('light');
    
    return (
        <ConfigProvider 
            theme={{ 
                algorithm: theme === 'light' ? antdTheme.defaultAlgorithm : antdTheme.darkAlgorithm,
            }}
        >
            <AppContent theme={theme} setTheme={setTheme} />
        </ConfigProvider>
    );
};


export default App;
