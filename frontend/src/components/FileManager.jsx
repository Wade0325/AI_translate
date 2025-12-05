import React, { useState, useRef } from 'react'; // <--- 引入 useRef
import {
  Card,
  Divider,
  Row,
  Col,
  Input,
  Button,
  message,
  Modal,
  Space, // <--- 引入 Space
} from 'antd';
import { UploadOutlined } from '@ant-design/icons'; // <--- 引入 UploadOutlined
import { useTranscription } from '../context/TranscriptionContext';
import UploadArea from './Transcription/UploadArea';
import FileQueueHeader from './Transcription/FileQueueHeader';
import FileQueueTable from './Transcription/FileQueueTable';
import QueueSummary from './Transcription/QueueSummary';

const { TextArea } = Input; // <--- 引入 TextArea

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

  // --- Modal 狀態管理 (保留) ---
  const [isTextModalVisible, setIsTextModalVisible] = useState(false);
  const [currentFile, setCurrentFile] = useState(null);
  const [currentText, setCurrentText] = useState("");
  const modalFileInputRef = useRef(null); // Modal 內的 file input

  // --- 新增：用於直接附加檔案的 ref 和 state ---
  const directFileInputRef = useRef(null);
  const [targetFileUid, setTargetFileUid] = useState(null);

  const handleOpenTextModal = (file) => {
    setCurrentFile(file);
    setCurrentText(file.original_text || "");
    setIsTextModalVisible(true);
  };

  const handleSaveText = () => {
    setFileList(list => list.map(f => {
      if (f.uid === currentFile.uid) {
        return { ...f, original_text: currentText, has_original_text: !!currentText };
      }
      return f;
    }));
    setIsTextModalVisible(false);
    setCurrentFile(null);
    setCurrentText("");
    message.success(`已為 "${currentFile.name}" 儲存附加文本。`);
  };

  const handleCancelTextModal = () => {
    setIsTextModalVisible(false);
    setCurrentFile(null);
    setCurrentText("");
  };

  // Modal 內的檔案選擇邏輯
  const handleModalFileSelect = (event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      setCurrentText(text);
      message.success(`已成功讀取檔案 "${file.name}" 的內容。`);
    };
    reader.onerror = () => {
      message.error(`讀取檔案 "${file.name}" 時發生錯誤。`);
    };
    reader.readAsText(file, 'UTF-8');
    
    // 清空 input 的值，以便下次可以選擇同一個檔案
    event.target.value = null;
  };

  // Modal 內的檔案選擇視窗觸發器
  const triggerModalFileSelect = () => {
    modalFileInputRef.current.click();
  };


  // --- 新增：處理直接檔案附加的函式 ---
  const handleDirectFileChange = (event) => {
    const file = event.target.files[0];
    if (!file || !targetFileUid) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      setFileList(list => list.map(f => {
        if (f.uid === targetFileUid) {
          return { ...f, original_text: text, has_original_text: !!text };
        }
        return f;
      }));
      message.success(`已成功為檔案附加文字稿 "${file.name}"`);
    };
    reader.onerror = () => {
      message.error(`讀取檔案 "${file.name}" 時發生錯誤。`);
    };
    reader.readAsText(file, 'UTF-8');
    
    event.target.value = null; // 清空以便下次選擇
    setTargetFileUid(null); // 重設 target uid
  };

  // --- 新增：觸發特定行的檔案選擇 ---
  const triggerDirectFileSelect = (uid) => {
    setTargetFileUid(uid); // 設定目標檔案的 UID
    directFileInputRef.current.click();
  };

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
      {/* --- 新增：隱藏的、用於直接附加的 input --- */}
      <input
        type="file"
        ref={directFileInputRef}
        style={{ display: 'none' }}
        onChange={handleDirectFileChange}
        accept=".txt,.lrc,.srt,.vtt,.ass"
      />
      
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
            onAttachText={handleOpenTextModal} // 這個是打開 Modal
            onAttachFileDirectly={triggerDirectFileSelect} // <--- 傳入新的函式
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
      {/* --- 新增的 Modal --- */}
      <Modal
        title={`為 "${currentFile?.name}" 附加文本`}
        open={isTextModalVisible}
        onOk={handleSaveText}
        onCancel={handleCancelTextModal}
        okText="儲存"
        cancelText="取消"
        width={700}
        destroyOnClose // 確保每次打開都是乾淨的
      >
        <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
          {/* --- 新增的檔案上傳區塊 --- */}
          <div>
            <input
              type="file"
              ref={modalFileInputRef}
              style={{ display: 'none' }}
              onChange={handleModalFileSelect}
              accept=".txt,.lrc,.srt,.vtt,.ass"
            />
            <Button icon={<UploadOutlined />} onClick={triggerModalFileSelect}>
              從檔案讀取文字
            </Button>
            <span style={{ marginLeft: 8, color: 'rgba(0,0,0,0.45)'}}>
              支援 .txt, .lrc, .srt, .vtt, .ass
            </span>
          </div>
          <p>或在此處貼上您完整的逐字稿。AI 將會為這份稿件配上時間戳。</p>
        </Space>
        
        <TextArea
          rows={15}
          value={currentText}
          onChange={(e) => setCurrentText(e.target.value)}
          placeholder="請在此貼上完整的逐字稿內容..."
        />
      </Modal>
    </Card>
  );
};

export default FileManager;
