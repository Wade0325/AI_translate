import { Button, Tag, Dropdown, Typography } from "antd"
import {
    FileAudio,
    ChevronDown,
    Download,
    Clock,
    Coins,
    Languages,
    Users,
} from "lucide-react"
import { downloadFormatsDetailed } from "@/constants/downloadFormats"
import { formatDuration } from "@/utils/formatters"

const { Text } = Typography

// Result 頁只會收到 completed 檔案（ResultPage 已過濾）
const COMPLETED_STYLE = {
    bg: 'rgba(45, 212, 168, 0.1)',
    iconColor: '#2dd4a8',
    borderColor: 'rgba(45, 212, 168, 0.3)',
    text: '#2dd4a8',
}

export function ResultFileCard({ file, onDownload }) {
    const fData = file._raw || file
    const sc = COMPLETED_STYLE

    const downloadMenuItems = [
        { key: 'header', type: 'group', label: <Text style={{ color: '#8888a8', fontSize: 12 }}>Choose format</Text> },
        { type: 'divider' },
        ...downloadFormatsDetailed.map((fmt) => ({
            key: fmt.key,
            label: (
                <div>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{fmt.label}</div>
                    <div style={{ fontSize: 11, color: '#8888a8' }}>{fmt.desc}</div>
                </div>
            ),
        })),
    ]

    return (
        <div style={{ borderRadius: 8, border: '1px solid #3a3a5c', background: '#1e1e3a', overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 12 }}>
                <div style={{
                    marginTop: 2,
                    width: 36,
                    height: 36,
                    flexShrink: 0,
                    borderRadius: 8,
                    background: sc.bg,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                }}>
                    <FileAudio size={16} color={sc.iconColor} />
                </div>

                <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {/* Row 1: filename + status */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Text ellipsis style={{ fontSize: 13, fontWeight: 600, color: '#e8e8e8' }}>{fData.name || file.name}</Text>
                        <Tag
                            bordered
                            style={{ fontSize: 10, padding: '0 6px', height: 16, lineHeight: '16px', borderColor: sc.borderColor, color: sc.text, background: 'transparent' }}
                        >
                            {fData.status || "completed"}
                        </Tag>
                    </div>

                    {/* Row 2: stats */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px' }}>
                        <StatChip icon={Languages} label={file.language || "Unknown"} />
                        <StatChip icon={Users} label={`${fData.speakerCount || 1} speaker(s)`} />
                        <StatChip icon={Clock} label={formatDuration(file.audioDurationSec || 0)} />
                        {fData.cost !== undefined && <StatChip icon={Coins} label={`$${fData.cost.toFixed(4)}`} highlight />}
                    </div>

                    {/* Row 3: token breakdown */}
                    <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 16,
                        borderRadius: 6,
                        background: 'rgba(42, 42, 72, 0.4)',
                        padding: '6px 10px',
                        width: 'fit-content',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 10, color: '#8888a8', textTransform: 'uppercase', letterSpacing: 0.5 }}>Total</span>
                            <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 500, color: '#e8e8e8' }}>
                                {fData.tokens_used?.toLocaleString() || file.totalTokens?.toLocaleString() || 0}
                            </span>
                        </div>
                        <div style={{ height: 12, width: 1, background: '#3a3a5c' }} />
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 10, color: '#8888a8', textTransform: 'uppercase', letterSpacing: 0.5 }}>Model</span>
                            <span style={{ fontSize: 12, fontWeight: 500, color: '#e8e8e8' }}>{file.model}</span>
                        </div>
                    </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                    <Dropdown
                        menu={{
                            items: downloadMenuItems,
                            onClick: ({ key }) => {
                                if (onDownload) {
                                    onDownload(fData.result?.[key], fData.name, key)
                                }
                            }
                        }}
                        placement="bottomRight"
                    >
                        <Button size="small" icon={<Download size={14} />}>
                            Download <ChevronDown size={12} />
                        </Button>
                    </Dropdown>
                </div>
            </div>
        </div>
    )
}

function StatChip({
    icon: Icon,
    label,
    highlight,
}) {
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 12,
            color: highlight ? '#2dd4a8' : '#8888a8',
            fontWeight: highlight ? 500 : 400,
        }}>
            <Icon size={12} />
            {label}
        </span>
    )
}
