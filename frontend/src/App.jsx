import React, { useState } from 'react';
import { Layout, Menu, theme } from 'antd';
import ModelManagerProvider from './components/ModelManager';
import Transcription from './components/Transcription';
import History from './components/History';
import { TranscriptionProvider } from './context/TranscriptionContext';
import { AudioOutlined, HistoryOutlined } from '@ant-design/icons';

const { Header, Content } = Layout;

const App = () => {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();

  const [activeKey, setActiveKey] = useState('transcription');

  return (
    <ModelManagerProvider>
      <TranscriptionProvider>
        <Layout>
          <Header>
            <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '0 24px', display: 'flex' }}>
              <Menu
                theme="dark"
                mode="horizontal"
                selectedKeys={[activeKey]}
                onClick={(e) => setActiveKey(e.key)}
                items={[
                  { key: 'transcription', label: '語音轉錄', icon: <AudioOutlined /> },
                  { key: 'history', label: '歷史紀錄', icon: <HistoryOutlined /> },
                ]}
                style={{ flex: 1, minWidth: 0, lineHeight: '64px' }}
              />
            </div>
          </Header>
          <Layout style={{ maxWidth: '1200px', width: '100%', margin: '0 auto', padding: '0 24px' }}>
            <Layout style={{ padding: '24px 0' }}>
              <Content
                style={{
                  padding: 24,
                  margin: 0,
                  minHeight: '85vh',
                  background: colorBgContainer,
                  borderRadius: borderRadiusLG,
                  overflow: 'auto',
                }}
              >
                {activeKey === 'transcription' && <Transcription />}
                {activeKey === 'history' && <History />}
              </Content>
            </Layout>
          </Layout>
        </Layout>
      </TranscriptionProvider>
    </ModelManagerProvider>
  );
};
export default App;
