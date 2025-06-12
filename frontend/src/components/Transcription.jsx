import React from 'react';
import { Typography } from 'antd';

const { Title } = Typography;

const Transcription = () => {
  return (
    <div>
      <Title level={2} style={{ marginBottom: '24px' }}>
        語音轉錄
      </Title>
      <p>這裡是未來放置語音轉錄功能的地方。</p>
    </div>
  );
};

export default Transcription;