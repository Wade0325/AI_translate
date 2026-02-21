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
  Switch,
  Tag,
  Alert,
} from 'antd';
import {
  AudioOutlined,
  EditOutlined,
  SlidersOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  HistoryOutlined,
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
  { value: 'ja-JP', label: '日文 (日本)' }
];

// --- 主要應用程式元件 ---
const Transcription = () => {
  const {
    fileList,
    model,
    setModel,
    targetLang,
    setTargetLang,
    targetTranslateLang,
    setTargetTranslateLang,
    isProcessing,
    useBatchMode,
    setUseBatchMode,
    handleStartTranscription,
    isPreviewModalVisible,
    previewContent,
    previewTitle,
    handleClosePreview,
    pendingBatches,
    isRecovering,
    recoverBatch,
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

      {/* --- 批次任務恢復提示 --- */}
      {pendingBatches.length > 0 && (
        <Alert
          type="info"
          showIcon
          icon={<HistoryOutlined />}
          message={`發現 ${pendingBatches.length} 個未完成的批次任務`}
          description={
            <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
              {pendingBatches.map(batch => (
                <Row key={batch.batch_id} align="middle" justify="space-between">
                  <Col>
                    <Text type="secondary">
                      {batch.files.length} 個檔案
                      {batch.files.length > 0 &&
                        ` (${batch.files.map(f => f.original_filename).slice(0, 3).join(', ')}${batch.files.length > 3 ? '...' : ''})`
                      }
                      {batch.created_at && ` — ${new Date(batch.created_at).toLocaleString()}`}
                    </Text>
                  </Col>
                  <Col>
                    <Button
                      type="primary"
                      size="small"
                      icon={<HistoryOutlined />}
                      loading={isRecovering}
                      onClick={() => recoverBatch(batch.batch_id)}
                    >
                      恢復結果
                    </Button>
                  </Col>
                </Row>
              ))}
            </Space>
          }
          closable
          style={{ marginBottom: 0 }}
        />
      )}

      {/* --- FileManager --- */}
      <FileManager />

      <Card title="2. 轉錄設定">
        <Row gutter={[16, 16]} align="bottom">
          <Col xs={24} sm={6}>
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
          <Col xs={24} sm={6}>
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
          <Col xs={24} sm={6}>
            <Text>音訊語言</Text>
            <Select value={targetLang} style={{ width: '100%' }} onChange={setTargetLang}>
              {languageOptions.map(lang => <Option key={lang.value} value={lang.value}>{lang.label}</Option>)}
            </Select>
          </Col>
          <Col xs={24} sm={6}>
            <Text>翻譯目標</Text>
            <Select
              value={targetTranslateLang}
              style={{ width: '100%' }}
              onChange={setTargetTranslateLang}
              allowClear
              placeholder="不翻譯"
            >
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
        <Row align="middle" justify="space-between" style={{ marginBottom: 12 }}>
          <Col>
            <Space align="center">
              <Tooltip title="啟用 Gemini Batch API，費用降為標準的 50%，但處理時間較長（通常數分鐘，最長 24 小時）。適合大量檔案且不急需結果的情境。">
                <Switch
                  checked={useBatchMode}
                  onChange={setUseBatchMode}
                  disabled={isProcessing}
                  checkedChildren={<ThunderboltOutlined />}
                />
              </Tooltip>
              <Text>批次模式</Text>
              {useBatchMode && (
                <Tag color="blue" style={{ marginLeft: 4 }}>費用 -50%</Tag>
              )}
            </Space>
          </Col>
          {useBatchMode && (
            <Col>
              <Text type="secondary" style={{ fontSize: 12 }}>
                所有檔案將合併為一個 Batch 任務送出，不支援 YouTube 連結
              </Text>
            </Col>
          )}
        </Row>
        <Button
          type="primary"
          icon={<AudioOutlined />}
          size="large"
          loading={isProcessing}
          onClick={handleStartTranscription}
          style={{ width: '100%' }}
          disabled={fileList.filter(f => f.status === 'waiting').length === 0}
        >
          {isProcessing
            ? '正在處理中...'
            : useBatchMode
              ? `批次轉錄 (${fileList.filter(f => f.status === 'waiting').length} 個新檔案)`
              : `開始轉錄 (${fileList.filter(f => f.status === 'waiting').length} 個新檔案)`
          }
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