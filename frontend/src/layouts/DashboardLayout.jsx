import { useState } from "react"
import { Outlet, useLocation } from "react-router-dom"
import { Layout, Typography } from "antd"
import { AppSidebar } from "@/components/app-sidebar"

const { Content, Header } = Layout
const { Title, Text } = Typography

const pageConfig = {
    "/": {
        title: "Dashboard",
        description: "Overview of your transcription activity and usage",
    },
    "/transcribe": {
        title: "New Transcription",
        description: "Configure global settings, upload files, and start transcription",
    },
    "/result": {
        title: "Transcription Results",
        description: "Browse and download your transcription results grouped by date.",
    },
    "/history": {
        title: "Transcription History",
        description: "Browse and manage all your past transcription jobs",
    },
    "/billing": {
        title: "Usage & Billing",
        description: "Track your token consumption, costs, and manage your subscription",
    },
    "/settings": {
        title: "Settings",
        description: "Manage your account and application preferences",
    },
}

export function DashboardLayout() {
    const { pathname } = useLocation()
    const config = pageConfig[pathname] || { title: "VoxScribe", description: "" }
    const [collapsed, setCollapsed] = useState(false)
    const [sidebarWidth, setSidebarWidth] = useState(240)

    return (
        <Layout style={{ minHeight: '100vh' }}>
            <AppSidebar
                collapsed={collapsed}
                onCollapse={setCollapsed}
                sidebarWidth={sidebarWidth}
                onSidebarResize={setSidebarWidth}
            />
            <Layout style={{ background: '#1a1a2e', overflow: 'hidden' }}>
                <Header style={{
                    background: '#1a1a2e',
                    borderBottom: '1px solid #3a3a5c',
                    padding: '16px 24px',
                    height: 'auto',
                    lineHeight: 1.4,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 16,
                    flexShrink: 0,
                }}>
                    <div>
                        <Title level={4} style={{ color: '#e8e8e8', margin: 0, fontSize: 18, lineHeight: 1.3 }}>
                            {config.title}
                        </Title>
                        {config.description && (
                            <Text style={{ color: '#8888a8', fontSize: 13 }}>
                                {config.description}
                            </Text>
                        )}
                    </div>
                    {/* Page-specific actions rendered via Outlet context */}
                    <div id="page-header-actions" />
                </Header>
                <Content style={{
                    flex: 1,
                    height: 0,
                    overflow: 'auto',
                    background: '#1a1a2e',
                    display: 'flex',
                    flexDirection: 'column',
                }}>
                    <Outlet />
                </Content>
            </Layout>
        </Layout>
    )
}
