import React from 'react';
import { Row, Col, Statistic } from 'antd';
import {
  CheckCircleOutlined,
  DashboardOutlined,
  DollarCircleOutlined,
} from '@ant-design/icons';

const QueueSummary = ({ completedFilesCount, totalTokens, totalCost }) => (
  <Row gutter={32} justify="end" style={{ marginTop: '16px', paddingRight: '8px' }}>
    <Col>
      <Statistic
        title={<span style={{ fontSize: '14px', color: 'rgba(0, 0, 0, 0.45)' }}>完成檔案</span>}
        value={completedFilesCount}
        valueStyle={{ fontSize: '20px' }}
        prefix={<CheckCircleOutlined />}
      />
    </Col>
    <Col>
      <Statistic
        title={<span style={{ fontSize: '14px', color: 'rgba(0, 0, 0, 0.45)' }}>總消耗 Tokens</span>}
        value={totalTokens}
        valueStyle={{ fontSize: '20px' }}
        prefix={<DashboardOutlined />}
      />
    </Col>
    <Col>
      <Statistic
        title={<span style={{ fontSize: '14px', color: 'rgba(0, 0, 0, 0.45)' }}>預估總花費 (USD)</span>}
        value={totalCost}
        precision={4}
        valueStyle={{ fontSize: '20px' }}
        prefix={<DollarCircleOutlined />}
      />
    </Col>
  </Row>
);

export default QueueSummary;
