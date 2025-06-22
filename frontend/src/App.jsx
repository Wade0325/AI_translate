import React, { useState } from 'react';
import { ApiOutlined, TranslationOutlined } from '@ant-design/icons';
import { Layout, Menu, theme } from 'antd';
import ModelManagerProvider, { ModelManagerDashboard } from './components/ModelManager';
import Transcription from './components/Transcription';
import { TranscriptionProvider } from './context/TranscriptionContext';

const { Header, Content, Sider } = Layout;
const items1 = ['1', '2', '3'].map((key) => ({
  key,
  label: `nav ${key}`,
}));
const items2 = [
  {
    key: `modelManager`,
    icon: React.createElement(ApiOutlined),
    label: '模型管理',
  },
  {
    key: `transcription`,
    icon: React.createElement(TranslationOutlined),
    label: '語音轉錄',
  },
];
const App = () => {
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();
  const [selectedKey, setSelectedKey] = useState('modelManager');

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
          <Header style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ marginLeft: '150px' }} className="demo-logo" />
            <Menu
              theme="dark"
              mode="horizontal"
              defaultSelectedKeys={['1']}
              items={items1}
              style={{ flex: 1, minWidth: 0 }}
            />
          </Header>
          <Layout>
            <Sider width={180} style={{ background: colorBgContainer }}>
              <Menu
                mode="inline"
                selectedKeys={[selectedKey]}
                onClick={({ key }) => setSelectedKey(key)}
                style={{ height: '100%', borderRight: 0 }}
                items={items2}
              />
            </Sider>
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