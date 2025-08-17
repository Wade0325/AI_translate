import React from 'react';
import { Upload } from 'antd';
import { UploadOutlined } from '@ant-design/icons';

const UploadArea = ({ uploadProps }) => (
  <Upload.Dragger {...uploadProps} height={200}>
    <p className="ant-upload-drag-icon">
      <UploadOutlined />
    </p>
    <p className="ant-upload-text">點擊或拖曳多個音訊/視訊檔案到此區域</p>
    <p className="ant-upload-hint">支援單次或批次上傳，上傳後列表將會取代此處。</p>
  </Upload.Dragger>
);

export default UploadArea;
