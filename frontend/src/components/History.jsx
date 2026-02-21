import React, { useState, useEffect, useCallback } from 'react';
import {
  Table,
  Card,
  Tag,
  Space,
  Button,
  Input,
  Select,
  Row,
  Col,
  Statistic,
  Modal,
  message,
  Typography,
  Tooltip,
  Popconfirm,
} from 'antd';
import {
  ReloadOutlined,
  DeleteOutlined,
  SearchOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DollarOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';

const { Text, Title } = Typography;
const { Option } = Select;

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// 狀態標籤顏色映射
const statusColorMap = {
  COMPLETED: 'success',
  FAILED: 'error',
  PROCESSING: 'processing',
};

// 格式化秒數
const formatDuration = (seconds) => {
  if (!seconds && seconds !== 0) return '-';
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(0);
  return `${mins} 分 ${secs} 秒`;
};

// 格式化費用
const formatCost = (cost) => {
  if (!cost && cost !== 0) return '-';
  return `$${cost.toFixed(6)}`;
};

// 格式化時間
const formatTime = (timestamp) => {
  if (!timestamp) return '-';
  try {
    return new Date(timestamp).toLocaleString('zh-TW');
  } catch {
    return timestamp;
  }
};

const History = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 15,
    total: 0,
  });
  const [filters, setFilters] = useState({
    status: null,
    is_batch: null,
    keyword: '',
  });

  // 載入統計資料
  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/history/stats`);
      if (response.ok) {
        const result = await response.json();
        setStats(result);
      }
    } catch (error) {
      console.error('載入統計資料失敗:', error);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  // 載入歷史紀錄
  const fetchHistory = useCallback(async (page = 1, pageSize = 15) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      });
      if (filters.status) params.append('status', filters.status);
      if (filters.is_batch !== null && filters.is_batch !== undefined) {
        params.append('is_batch', filters.is_batch.toString());
      }
      if (filters.keyword) params.append('keyword', filters.keyword);

      const response = await fetch(`${API_BASE_URL}/history?${params}`);
      if (response.ok) {
        const result = await response.json();
        setData(result.items);
        setPagination({
          current: result.page,
          pageSize: result.page_size,
          total: result.total,
        });
      }
    } catch (error) {
      console.error('載入歷史紀錄失敗:', error);
      message.error('載入歷史紀錄失敗');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchHistory();
    fetchStats();
  }, []);

  // 刪除紀錄
  const handleDelete = async (taskUuid) => {
    try {
      const response = await fetch(`${API_BASE_URL}/history/${taskUuid}`, {
        method: 'DELETE',
      });
      if (response.ok) {
        message.success('已刪除紀錄');
        fetchHistory(pagination.current, pagination.pageSize);
        fetchStats();
      } else {
        message.error('刪除失敗');
      }
    } catch (error) {
      message.error('刪除失敗');
    }
  };

  // 搜尋
  const handleSearch = () => {
    fetchHistory(1, pagination.pageSize);
  };

  // 重置篩選
  const handleReset = () => {
    setFilters({ status: null, is_batch: null, keyword: '' });
    fetchHistory(1, pagination.pageSize);
    fetchStats();
  };

  // 表格分頁
  const handleTableChange = (paginationConfig) => {
    fetchHistory(paginationConfig.current, paginationConfig.pageSize);
  };

  // 展開列：顯示詳細資訊
  const expandedRowRender = (record) => (
    <Row gutter={[16, 8]}>
      <Col span={6}>
        <Text type="secondary">任務 ID：</Text>
        <br />
        <Text copyable style={{ fontSize: 12 }}>{record.task_uuid}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">模型：</Text>
        <br />
        <Text>{record.model_used || '-'}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">服務商：</Text>
        <br />
        <Text>{record.provider || '-'}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">音訊語言：</Text>
        <br />
        <Text>{record.source_language || '-'}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">翻譯目標：</Text>
        <br />
        <Text>{record.target_language || '未翻譯'}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">Token 用量：</Text>
        <br />
        <Text>{record.total_tokens?.toLocaleString() || '-'}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">音檔長度：</Text>
        <br />
        <Text>{formatDuration(record.audio_duration_seconds)}</Text>
      </Col>
      <Col span={6}>
        <Text type="secondary">批次 ID：</Text>
        <br />
        <Text style={{ fontSize: 12 }}>{record.batch_id || '-'}</Text>
      </Col>
      {record.error_message && (
        <Col span={24}>
          <Text type="secondary">錯誤訊息：</Text>
          <br />
          <Text type="danger" style={{ fontSize: 12 }}>
            {record.error_message}
          </Text>
        </Col>
      )}
    </Row>
  );

  // 表格欄位定義
  const columns = [
    {
      title: '檔案名稱',
      dataIndex: 'original_filename',
      key: 'original_filename',
      ellipsis: true,
      width: '22%',
      render: (text) => (
        <Tooltip title={text}>
          <Text strong style={{ fontSize: 13 }}>
            <FileTextOutlined style={{ marginRight: 6, color: '#1677ff' }} />
            {text || '-'}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '狀態',
      dataIndex: 'status',
      key: 'status',
      width: '10%',
      render: (status) => (
        <Tag color={statusColorMap[status] || 'default'}>
          {status || '-'}
        </Tag>
      ),
    },
    {
      title: '模式',
      dataIndex: 'is_batch',
      key: 'is_batch',
      width: '8%',
      render: (isBatch) =>
        isBatch ? (
          <Tag icon={<ThunderboltOutlined />} color="blue">
            批次
          </Tag>
        ) : (
          <Tag color="default">一般</Tag>
        ),
    },
    {
      title: '開始時間',
      dataIndex: 'request_timestamp',
      key: 'request_timestamp',
      width: '16%',
      render: (ts) => (
        <Text style={{ fontSize: 12 }}>{formatTime(ts)}</Text>
      ),
    },
    {
      title: '處理耗時',
      dataIndex: 'processing_time_seconds',
      key: 'processing_time_seconds',
      width: '10%',
      render: (seconds) => (
        <Text style={{ fontSize: 12 }}>{formatDuration(seconds)}</Text>
      ),
    },
    {
      title: '費用',
      dataIndex: 'cost',
      key: 'cost',
      width: '10%',
      render: (cost) => (
        <Text style={{ fontSize: 12, color: cost > 0 ? '#52c41a' : undefined }}>
          {formatCost(cost)}
        </Text>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model_used',
      key: 'model_used',
      width: '14%',
      ellipsis: true,
      render: (model) => (
        <Text style={{ fontSize: 12 }}>{model || '-'}</Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: '10%',
      render: (_, record) => (
        <Popconfirm
          title="確定要刪除這筆紀錄嗎？"
          onConfirm={() => handleDelete(record.task_uuid)}
          okText="確定"
          cancelText="取消"
        >
          <Button danger size="small" icon={<DeleteOutlined />}>
            刪除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* 統計卡片 */}
      {stats && (
        <Row gutter={[16, 16]}>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="總任務數"
                value={stats.total_tasks}
                prefix={<FileTextOutlined />}
                loading={statsLoading}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="成功率"
                value={stats.success_rate}
                suffix="%"
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: stats.success_rate >= 90 ? '#3f8600' : '#cf1322' }}
                loading={statsLoading}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="總費用"
                value={stats.total_cost}
                precision={4}
                prefix={<DollarOutlined />}
                loading={statsLoading}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="平均處理時間"
                value={stats.avg_processing_time_seconds}
                precision={1}
                suffix="秒"
                prefix={<ClockCircleOutlined />}
                loading={statsLoading}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 篩選列 */}
      <Card size="small">
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={7}>
            <Input
              placeholder="搜尋檔案名稱或模型..."
              prefix={<SearchOutlined />}
              value={filters.keyword}
              onChange={(e) =>
                setFilters((prev) => ({ ...prev, keyword: e.target.value }))
              }
              onPressEnter={handleSearch}
              allowClear
            />
          </Col>
          <Col xs={12} sm={4}>
            <Select
              placeholder="狀態"
              style={{ width: '100%' }}
              value={filters.status}
              onChange={(val) =>
                setFilters((prev) => ({ ...prev, status: val }))
              }
              allowClear
            >
              <Option value="COMPLETED">成功</Option>
              <Option value="FAILED">失敗</Option>
              <Option value="PROCESSING">處理中</Option>
            </Select>
          </Col>
          <Col xs={12} sm={4}>
            <Select
              placeholder="模式"
              style={{ width: '100%' }}
              value={filters.is_batch}
              onChange={(val) =>
                setFilters((prev) => ({ ...prev, is_batch: val }))
              }
              allowClear
            >
              <Option value={true}>批次</Option>
              <Option value={false}>一般</Option>
            </Select>
          </Col>
          <Col xs={24} sm={9}>
            <Space>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                搜尋
              </Button>
              <Button icon={<ReloadOutlined />} onClick={handleReset}>
                重置
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 主表格 */}
      <Table
        columns={columns}
        dataSource={data}
        rowKey="task_uuid"
        loading={loading}
        pagination={{
          ...pagination,
          showSizeChanger: true,
          pageSizeOptions: ['10', '15', '20', '50'],
          showTotal: (total) => `共 ${total} 筆紀錄`,
        }}
        onChange={handleTableChange}
        expandable={{
          expandedRowRender,
          expandRowByClick: true,
        }}
        size="middle"
        scroll={{ x: 900 }}
      />
    </Space>
  );
};

export default History;
