import React, { useState, useEffect } from 'react';
import {
  Button,
  Select,
  Typography,
  Space,
  Row,
  Col,
  Card,
  Tooltip,
  Modal,
} from 'antd';
import {
  AudioOutlined,
  EditOutlined,
  SlidersOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { useTranscription } from '../context/TranscriptionContext';
import { useModelManager } from './ModelManager';
import { modelOptions, findProviderForModel } from '../constants/modelConfig';
import FileManager from './FileManager';

const { Text } = Typography;
const { Option } = Select;

// --- 語言和格式選項 (保持不變) ---
const languageOptions = [
  { value: 'zh-TW', label: '繁體中文 (台灣)' },
  { value: 'en-US', label: '英文 (美國)' },
];

// --- 主要應用程式元件 ---
const Transcription = () => {
  const {
    fileList,
    model,
    setModel,
    targetLang,
    setTargetLang,
    isProcessing,
    handleStartTranscription,
    isPreviewModalVisible,
    previewContent,
    previewTitle,
    handleClosePreview,
  } = useTranscription();
  
  const { handleEditProvider, handleEditProviderParams, handleTestProvider } = useModelManager();

  const [selectedProvider, setSelectedProvider] = useState(() => findProviderForModel(model));

  useEffect(() => {
    const provider = findProviderForModel(model);
    setSelectedProvider(provider);
  }, [model]);

  // 處理服務商變更的事件
  const handleProviderChange = (newProvider) => {
    setSelectedProvider(newProvider);
    // 當服務商變更時，自動選擇該服務商的第一個模型
    const defaultModel = modelOptions[newProvider]?.[0]?.value;
    if (defaultModel) {
      setModel(defaultModel);
    } else {
      setModel(null); // 如果該服務商沒有模型，則清空
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      
      {/* --- FileManager --- */}
      <FileManager />

      <Card title="2. 轉錄設定">
        <Row gutter={[16, 16]} align="bottom">
          <Col xs={24} sm={8}>
            <Text>選擇服務商</Text>
            <Select
              value={selectedProvider}
              style={{ width: '100%' }}
              onChange={handleProviderChange}
            >
              {Object.keys(modelOptions).map(provider => (
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
              {modelOptions[selectedProvider]?.map(option => (
                  <Option key={option.value} value={option.value}>{option.label}</Option>
              ))}
            </Select>
          </Col>
          <Col xs={24} sm={8}>
            <Text>輸出語言</Text>
            <Select value={targetLang} style={{ width: '100%' }} onChange={setTargetLang}>
              {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
            </Select>
          </Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: '8px' }}>
          <Col xs={24} sm={8}>
            <Space.Compact style={{ width: '100%' }}>
              <Tooltip title="編輯API金鑰與模型" placement="bottom">
                <Button
                  icon={<EditOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleEditProvider(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  編輯API
                </Button>
              </Tooltip>
              <Tooltip title="編輯 Prompt 參數" placement="bottom">
                <Button
                  icon={<SlidersOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleEditProviderParams(selectedProvider)}
                  disabled={!selectedProvider}
                >
                  編輯參數
                </Button>
              </Tooltip>
              <Tooltip title="測試此API是否可用" placement="bottom">
                <Button
                  icon={<PlayCircleOutlined />}
                  style={{ width: '33.33%' }}
                  onClick={() => handleTestProvider(selectedProvider)}
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

      {/* --- Modal 現在直接從 Context 獲取狀態 --- */}
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