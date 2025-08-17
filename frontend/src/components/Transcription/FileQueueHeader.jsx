import React from 'react';
import { Row, Col, Typography, Space, Upload, Button, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';

const { Title } = Typography;

const FileQueueHeader = ({ uploadProps, onClearAllFiles, hasFiles }) => (
  <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
    <Col>
      <Title level={5} style={{ margin: 0 }}>本次任務佇列</Title>
    </Col>
    <Col>
      <Space>
        <Upload {...uploadProps}>
          <Button icon={<PlusOutlined />}>新增檔案</Button>
        </Upload>
        {hasFiles && (
          <Popconfirm
            title="確定要清除所有任務嗎？"
            onConfirm={onClearAllFiles}
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
);

export default FileQueueHeader;
