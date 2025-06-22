import React, { useState } from 'react';
import { Layout, Menu, theme } from 'antd';
import ModelManagerProvider, { ModelManagerDashboard } from './components/ModelManager';
import Transcription from './components/Transcription';
import { TranscriptionProvider } from './context/TranscriptionContext';

const { Header, Content } = Layout;
const items1 = ['1'].map((key) => ({
  key,
  label: '語音轉錄',
}));

const App = () => {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();
  const [selectedKey, setSelectedKey] = useState('transcription');

  const renderContent = () => {
    switch (selectedKey) {
      case 'modelManager':
        return <ModelManagerDashboard />;
      case 'transcription':
        return <Transcription />;
      default:
        return <ModelManagerDashboard />;
    }
  };

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
              items={items1}
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
                {renderContent()}
              </Content>
            </Layout>
          </Layout>
        </Layout>
      </TranscriptionProvider>
    </ModelManagerProvider>
  );
};
export default App;