import React, { useState } from 'react';
import {
  Card,
  Divider,
  Row,
  Col,
  Input,
  Button,
  message,
} from 'antd';
import { useTranscription } from '../context/TranscriptionContext';
import UploadArea from './Transcription/UploadArea';
import FileQueueHeader from './Transcription/FileQueueHeader';
import FileQueueTable from './Transcription/FileQueueTable';
import QueueSummary from './Transcription/QueueSummary';

const FileManager = () => {
  // 從 Context 直接獲取所有需要的狀態和函式
  const {
    fileList,
    setFileList,
    handleUploadChange,
    downloadFile,
    clearAllFiles,
    handleReprocess,
    handleOpenPreview, // 從 Context 獲取打開預覽的函式
  } = useTranscription();
  
  // 將 YT 連結相關的 state 獨立在此元件內部
  const [youtubeUrl, setYoutubeUrl] = useState('');

  // 將新增 YT 連結的邏輯移入此元件
  const handleAddYoutubeUrl = () => {
    if (!youtubeUrl.trim()) {
      message.warning('請輸入 YouTube 連結');
      return;
    }
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
      size: 0, 
      originFileObj: null,
      statusText: '等待處理', // 新增
    };

    setFileList(list => [...list, newFile]);
    setYoutubeUrl(''); 
    message.success('已成功將 YouTube 連結加入佇列');
  };
  
  // 將移除檔案的邏輯移入此元件
  const handleRemoveFile = (uid) => {
    setFileList(list => list.filter(f => f.uid !== uid));
  };

  // Upload 元件所需的 props
  const uploadProps = {
    multiple: true,
    fileList,
    onChange: handleUploadChange,
    beforeUpload: () => false,
    showUploadList: false,
    accept: 'audio/*',
  };
  
  // 計算總結數據
  const completedFilesCount = fileList.filter(f => f.status === 'completed').length;
  const totalTokens = fileList
    .filter(f => f.status === 'completed')
    .reduce((acc, file) => acc + (file.tokens_used || 0), 0);
  const totalCost = fileList
    .filter(f => f.status === 'completed')
    .reduce((acc, file) => acc + (file.cost || 0), 0);

  return (
    <Card title="1. 上傳與管理檔案">
      {fileList.length === 0 ? (
        <UploadArea uploadProps={uploadProps} />
      ) : (
        <div>
          <FileQueueHeader
            uploadProps={uploadProps}
            onClearAllFiles={clearAllFiles}
            hasFiles={fileList.length > 0}
          />
          <FileQueueTable
            dataSource={fileList}
            onDownloadFile={downloadFile}
            onReprocessFile={handleReprocess}
            onRemoveFile={handleRemoveFile}
            onPreviewFile={handleOpenPreview}
          />
          <QueueSummary
            completedFilesCount={completedFilesCount}
            totalTokens={totalTokens}
            totalCost={totalCost}
          />
        </div>
      )}
      <Divider />
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
  );
};

export default FileManager;
