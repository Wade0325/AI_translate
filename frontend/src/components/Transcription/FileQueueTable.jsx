import React from 'react';
import { Table, Tooltip, Space, Button, Popconfirm, Tag, Spin, Dropdown, Menu } from 'antd'; // <--- 引入 Dropdown 和 Menu
import {
  EyeOutlined,
  ReloadOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
  FileTextOutlined,
  DownloadOutlined, // <--- 引入下載圖示
  UploadOutlined, // <--- 引入 UploadOutlined
} from '@ant-design/icons';

const FileQueueTable = ({
  dataSource,
  onDownloadFile,
  onReprocessFile,
  onRemoveFile,
  onPreviewFile,
  onAttachText, // Modal 的函式
  onAttachFileDirectly, // <--- 接收新的 prop
}) => {
  const fileListColumns = [
    { 
      title: '檔案名稱', 
      dataIndex: 'name', 
      key: 'name', 
      width: '33%',
      render: (name, record) => ( // <--- 修改 render 函式
        <Tooltip title={name} popupStyle={{ maxWidth: '600px' }}>
          <Space>
            {record.has_original_text && (
              <Tooltip title="此檔案已附加文本，將執行對齊任務">
                <FileTextOutlined style={{ color: '#1890ff' }} />
              </Tooltip>
            )}
            <span style={{
              display: 'block',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {name}
            </span>
          </Space>
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
      width: '22%', // 稍微調整寬度以容納新按鈕
      render: (_, record) => {
        const availableFormats = ['lrc', 'srt', 'vtt', 'txt'];

        // --- 建立下載選單 ---
        const downloadMenu = (
          <Menu>
            {availableFormats.map(format => (
              <Menu.Item
                key={format}
                disabled={!record.result?.[format]}
                onClick={() => onDownloadFile(record.result[format], record.name, format)}
              >
                下載 {format.toUpperCase()}
              </Menu.Item>
            ))}
          </Menu>
        );

        return (
          <Space>
            <Tooltip title={record.has_original_text ? "編輯附加文本" : "貼上文本"}>
              <Button
                size="small"
                icon={<FileTextOutlined />}
                onClick={() => onAttachText(record)}
                disabled={record.status === 'processing'}
                type={record.has_original_text ? "primary" : "default"}
                ghost={record.has_original_text}
              />
            </Tooltip>
            
            {/* --- 新增的直接附加檔案按鈕 --- */}
            <Tooltip title="從檔案附加文本">
              <Button
                size="small"
                icon={<UploadOutlined />}
                onClick={() => onAttachFileDirectly(record.uid)}
                disabled={record.status === 'processing'}
              />
            </Tooltip>

            {record.status === 'completed' && record.result?.txt && (
              <Tooltip title="預覽內容">
                <Button
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => onPreviewFile(record)}
                />
              </Tooltip>
            )}

            {/* --- 使用 Dropdown 取代原本的按鈕列表 --- */}
            {record.status === 'completed' && record.result && (
              <Dropdown overlay={downloadMenu} placement="bottom">
                <Button size="small" icon={<DownloadOutlined />}>
                  下載
                </Button>
              </Dropdown>
            )}

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
