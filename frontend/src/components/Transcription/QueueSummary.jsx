import React from 'react';
import { Row, Col, Statistic, Dropdown, Button } from 'antd';
import {
  CheckCircleOutlined,
  DashboardOutlined,
  DollarCircleOutlined,
  DownloadOutlined,
  DownOutlined,
} from '@ant-design/icons';
import { useTranscription } from '../../context/TranscriptionContext';

const QueueSummary = ({ completedFilesCount, totalTokens, totalCost }) => {
  const { downloadAllFiles } = useTranscription();

  const downloadMenuItems = [
    {
      key: 'lrc',
      label: 'LRC 字幕檔',
      onClick: () => downloadAllFiles('lrc'),
    },
    {
      key: 'srt',
      label: 'SRT 字幕檔',
      onClick: () => downloadAllFiles('srt'),
    },
    {
      key: 'vtt',
      label: 'VTT 字幕檔', 
      onClick: () => downloadAllFiles('vtt'),
    },
    {
      key: 'txt',
      label: 'TXT 文字檔',
      onClick: () => downloadAllFiles('txt'),
    },
  ];

  return (
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
      {completedFilesCount > 0 && (
        <Col style={{ display: 'flex', alignItems: 'center', marginTop: '8px' }}>
          <Dropdown
            menu={{ items: downloadMenuItems }}
            placement="bottomRight"
            disabled={completedFilesCount === 0}
          >
            <Button 
              type="primary" 
              icon={<DownloadOutlined />}
              style={{ marginLeft: '16px' }}
            >
              下載全部 <DownOutlined />
            </Button>
          </Dropdown>
        </Col>
      )}
    </Row>
  );
};

export default QueueSummary;
