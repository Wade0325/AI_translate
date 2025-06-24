import React from 'react';
import { Layout, Menu, theme } from 'antd';
import ModelManagerProvider from './components/ModelManager';
import Transcription from './components/Transcription';
import { TranscriptionProvider } from './context/TranscriptionContext';

const { Header, Content } = Layout;

const App = () => {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();

  return (
    <ModelManagerProvider>
      <TranscriptionProvider>
        <Layout>
          <Header style={{ display: 'flex'}}>
            <div style={{ marginLeft: '270px' }}/>
            <Menu
              theme="dark"
              mode="horizontal"
              defaultSelectedKeys={['1']}
              items={[{ key: '1', label: '語音轉錄' }]}
              style={{ flex: 1, minWidth: 0 }}
            />
          </Header>
          <Layout style={{ padding: '0 15%' }}>
            <Layout style={{ padding: '0 24px 24px' }}>
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
                <Transcription />
              </Content>
            </Layout>
          </Layout>
        </Layout>
      </TranscriptionProvider>
    </ModelManagerProvider>
  );
};
export default App;