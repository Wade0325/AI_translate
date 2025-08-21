import React from 'react';
import { Table, Tooltip, Space, Progress, Button, Popconfirm, Tag, Spin } from 'antd';
import {
  EyeOutlined,
  ReloadOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';

const FileQueueTable = ({
  dataSource,
  onDownloadFile,
  onReprocessFile,
  onRemoveFile,
  onPreviewFile,
}) => {
  const fileListColumns = [
    { 
      title: '檔案名稱', 
      dataIndex: 'name', 
      key: 'name', 
      width: '33%',
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
      width: '10%',
      render: (size) => `${(size / 1024 / 1024).toFixed(2)} MB` 
    },
    {
      title: 'Tokens',
      dataIndex: 'tokens_used',
      key: 'tokens_used',
      width: '10%',
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
      width: '10%',
      render: (cost, record) => (record.status === 'completed' && cost ? `$${cost.toFixed(4)}` : '-'),
    },
    {
      title: '進度',
      dataIndex: 'status',
      key: 'status',
      width: '15%',
      render: (status, record) => {
        switch (status) {
          case 'processing':
            return (
              <Space>
                <Spin size="small" />
                <Tooltip title={record.statusText}>
                  <span style={{
                      display: 'inline-block',
                      maxWidth: '120px',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      verticalAlign: 'middle'
                  }}>
                    {record.statusText || '處理中...'}
                  </span>
                </Tooltip>
              </Space>
            );
          case 'completed':
            return <Tag color="success">完成</Tag>;
          case 'error':
            return (
              <Tooltip title={record.error || '未知錯誤'}>
                <Tag color="error">失敗</Tag>
              </Tooltip>
            );
          case 'waiting':
          default:
            return <Tag>等待中</Tag>;
        }
      },
    },
    {
      title: '操作',
      key: 'action',
      width: '25%',
      render: (_, record) => {
        const availableFormats = ['lrc', 'srt', 'vtt', 'txt'];
        return (
          <Space>
            {record.status === 'completed' && record.result?.txt && (
              <Tooltip title="預覽內容">
                <Button
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => onPreviewFile(record)}
                />
              </Tooltip>
            )}
            {record.status === 'completed' && record.result && availableFormats.map(format => (
              <Tooltip title={`下載 ${format.toUpperCase()}`} key={format}>
                <Button
                  size="small"
                  onClick={() => onDownloadFile(record.result[format], record.name, format)}
                  disabled={!record.result[format]}
                >
                  {format.toUpperCase()}
                </Button>
              </Tooltip>
            ))}
            {(record.status === 'completed' || record.status === 'error') && (
              <Tooltip title="重新處理">
                <Popconfirm
                  title="確定要重新處理此任務嗎?"
                  onConfirm={() => onReprocessFile(record.uid)}
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
                  onClick={() => onRemoveFile(record.uid)}
              />
             </Tooltip>
          </Space>
        );
      }
    },
  ];

  return (
    <Table
      size="small"
      columns={fileListColumns}
      dataSource={dataSource}
      rowKey="uid"
      pagination={{ pageSize: 5 }}
      tableLayout="fixed"
    />
  );
};

export default FileQueueTable;
