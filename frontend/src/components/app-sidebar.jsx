import { useState, useRef, useCallback, useEffect } from "react"
import { Link, useLocation } from "react-router-dom"
import {
    LayoutDashboard,
    Upload,
    FileText,
    History,
    CreditCard,
    Settings,
    AudioWaveform,
} from "lucide-react"
import { Layout, Menu, Avatar, Typography } from "antd"
import {
    MenuFoldOutlined,
    MenuUnfoldOutlined,
} from "@ant-design/icons"

const { Sider } = Layout
const { Text } = Typography

const mainNav = [
    { title: "Dashboard", icon: LayoutDashboard, href: "/" },
    { title: "New Transcription", icon: Upload, href: "/transcribe" },
    { title: "Result Viewer", icon: FileText, href: "/result" },
    { title: "History", icon: History, href: "/history" },
]

const systemNav = [
    { title: "Usage & Billing", icon: CreditCard, href: "/billing" },
    { title: "Settings", icon: Settings, href: "/settings" },
]

export function AppSidebar({ collapsed, onCollapse, sidebarWidth = 240, onSidebarResize }) {
    const { pathname } = useLocation()
    const isResizing = useRef(false)
    const handleRef = useRef(null)

    const handleMouseDown = useCallback((e) => {
        e.preventDefault()
        isResizing.current = true
        document.body.classList.add('sidebar-resizing')
        if (handleRef.current) handleRef.current.classList.add('active')
    }, [])

    useEffect(() => {
        const handleMouseMove = (e) => {
            if (!isResizing.current) return
            const newWidth = Math.min(480, Math.max(180, e.clientX))
            onSidebarResize?.(newWidth)
        }
        const handleMouseUp = () => {
            if (!isResizing.current) return
            isResizing.current = false
            document.body.classList.remove('sidebar-resizing')
            if (handleRef.current) handleRef.current.classList.remove('active')
        }
        document.addEventListener('mousemove', handleMouseMove)
        document.addEventListener('mouseup', handleMouseUp)
        return () => {
            document.removeEventListener('mousemove', handleMouseMove)
            document.removeEventListener('mouseup', handleMouseUp)
        }
    }, [onSidebarResize])

    const mainItems = mainNav.map((item) => ({
        key: item.href,
        icon: <item.icon size={16} />,
        label: <Link to={item.href}>{item.title}</Link>,
    }))

    const systemItems = systemNav.map((item) => ({
        key: item.href,
        icon: <item.icon size={16} />,
        label: <Link to={item.href}>{item.title}</Link>,
    }))

    return (
        <Sider
            collapsible
            collapsed={collapsed}
            onCollapse={onCollapse}
            width={sidebarWidth}
            collapsedWidth={64}
            trigger={null}
            style={{
                background: '#141428',
                borderRight: '1px solid #2a2a48',
                display: 'flex',
                flexDirection: 'column',
                height: '100vh',
                position: 'sticky',
                top: 0,
                left: 0,
            }}
        >
            {/* Resize handle */}
            {!collapsed && (
                <div
                    ref={handleRef}
                    className="sidebar-resize-handle"
                    onMouseDown={handleMouseDown}
                />
            )}
            {/* Logo area */}
            <div style={{
                padding: collapsed ? '16px 12px' : '16px 20px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                borderBottom: '1px solid #2a2a48',
                minHeight: 56,
            }}>
                <div style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    background: '#2dd4a8',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                }}>
                    <AudioWaveform size={16} color="#141428" />
                </div>
                {!collapsed && (
                    <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                        <Text strong style={{ color: '#e8e8e8', fontSize: 14 }}>VoxScribe</Text>
                        <Text style={{ color: '#8888a8', fontSize: 11 }}>AI Transcription</Text>
                    </div>
                )}
            </div>

            {/* Main nav */}
            <div style={{ flex: 1, overflow: 'auto', paddingTop: 8 }}>
                <div style={{ padding: collapsed ? '4px 0' : '4px 12px 4px 20px' }}>
                    {!collapsed && (
                        <Text style={{ color: '#6868888', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>
                            Main
                        </Text>
                    )}
                </div>
                <Menu
                    mode="inline"
                    theme="dark"
                    selectedKeys={[pathname]}
                    items={mainItems}
                    style={{ background: 'transparent', borderRight: 0 }}
                />

                <div style={{ padding: collapsed ? '12px 0 4px' : '12px 12px 4px 20px' }}>
                    {!collapsed && (
                        <Text style={{ color: '#6868888', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>
                            System
                        </Text>
                    )}
                </div>
                <Menu
                    mode="inline"
                    theme="dark"
                    selectedKeys={[pathname]}
                    items={systemItems}
                    style={{ background: 'transparent', borderRight: 0 }}
                />
            </div>

            {/* Footer - user info */}
            <div style={{
                borderTop: '1px solid #2a2a48',
                padding: collapsed ? '12px 16px' : '12px 20px',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
            }}>
                <Avatar
                    size={32}
                    style={{ background: 'rgba(45, 212, 168, 0.2)', color: '#2dd4a8', fontSize: 12, flexShrink: 0 }}
                >
                    US
                </Avatar>
                {!collapsed && (
                    <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                        <Text style={{ color: '#e8e8e8', fontSize: 13, fontWeight: 500 }}>User</Text>
                        <Text style={{ color: '#8888a8', fontSize: 11 }}>Free Plan</Text>
                    </div>
                )}
            </div>

            {/* Collapse trigger */}
            <div
                style={{
                    borderTop: '1px solid #2a2a48',
                    padding: '8px 0',
                    textAlign: 'center',
                    cursor: 'pointer',
                    color: '#8888a8',
                }}
                onClick={() => onCollapse(!collapsed)}
            >
                {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </div>
        </Sider>
    )
}
