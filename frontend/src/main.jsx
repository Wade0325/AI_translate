import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')).render(
    <StrictMode>
        <ConfigProvider
            theme={{
                algorithm: theme.darkAlgorithm,
                token: {
                    colorPrimary: '#2dd4a8',
                    colorBgContainer: '#1e1e3a',
                    colorBgElevated: '#1e1e3a',
                    colorBgLayout: '#1a1a2e',
                    colorBorder: '#3a3a5c',
                    colorBorderSecondary: '#2a2a48',
                    colorText: '#e8e8e8',
                    colorTextSecondary: '#8888a8',
                    colorTextTertiary: '#6868888',
                    colorError: '#e05252',
                    colorWarning: '#d4a72d',
                    colorSuccess: '#2dd480',
                    colorInfo: '#2dd4a8',
                    borderRadius: 8,
                    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
                    fontFamilyCode: "'JetBrains Mono', 'Fira Code', monospace",
                },
                components: {
                    Layout: {
                        siderBg: '#141428',
                        headerBg: '#1a1a2e',
                        bodyBg: '#1a1a2e',
                        triggerBg: '#1e1e3a',
                    },
                    Menu: {
                        darkItemBg: '#141428',
                        darkSubMenuItemBg: '#141428',
                        darkItemSelectedBg: '#2dd4a820',
                        darkItemHoverBg: '#1e1e3a',
                    },
                    Card: {
                        colorBgContainer: '#1e1e3a',
                        colorBorderSecondary: '#3a3a5c',
                    },
                    Table: {
                        colorBgContainer: '#1e1e3a',
                        headerBg: '#1a1a2e',
                        rowHoverBg: '#24243e',
                        borderColor: '#3a3a5c',
                    },
                    Input: {
                        colorBgContainer: '#1a1a2e',
                        colorBorder: '#3a3a5c',
                    },
                    Select: {
                        colorBgContainer: '#1a1a2e',
                        colorBorder: '#3a3a5c',
                    },
                    Tabs: {
                        colorBorderSecondary: '#3a3a5c',
                    },
                    Modal: {
                        contentBg: '#1e1e3a',
                        headerBg: '#1e1e3a',
                    },
                },
            }}
        >
            <BrowserRouter>
                <App />
            </BrowserRouter>
        </ConfigProvider>
    </StrictMode>,
)
