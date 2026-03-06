import { useState } from "react"
import { Button, Tag, Dropdown, Typography, Space } from "antd"
import {
    FileAudio,
    ChevronDown,
    Download,
    Clock,
    Cpu,
    Coins,
    Zap,
    Languages,
    Users,
    Timer,
    Eye,
    Copy,
    Check,
} from "lucide-react"

const { Text } = Typography

const DOWNLOAD_FORMATS = [
    { label: "SRT (Subtitles)", ext: "srt", desc: "SubRip format with timestamps" },
    { label: "VTT (WebVTT)", ext: "vtt", desc: "Web Video Text Tracks" },
    { label: "TXT (Plain Text)", ext: "txt", desc: "Plain text without timestamps" },
    { label: "JSON (Structured)", ext: "json", desc: "Structured data with metadata" },
    { label: "LRC (Lyrics)", ext: "lrc", desc: "Lyrics format" },
]

function formatTime(seconds) {
    if (!seconds) return "0:00"
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    return `${m}:${s.toString().padStart(2, "0")}`
}

export function ResultFileCard({ file, onDownload }) {
    const [expanded, setExpanded] = useState(false)
    const [copiedId, setCopiedId] = useState(null)

    // Ensure we are working with the _raw file data passed from ResultPage
    const fData = file._raw || file

    // Extract segments if available
    const segments = fData.result?.json?.segments || []

    const handleCopy = (id, text) => {
        navigator.clipboard.writeText(text)
        setCopiedId(id)
        setTimeout(() => setCopiedId(null), 1500)
    }

    const handleCopyAll = () => {
        const fullText = segments
            .map((s) => `[${formatTime(s.start)}] ${s.speaker || "Speaker"}: ${s.text}`)
            .join("\n")
        navigator.clipboard.writeText(fullText)
        setCopiedId("all")
        setTimeout(() => setCopiedId(null), 1500)
    }

    const statusColors = {
        completed: { bg: 'rgba(45, 212, 168, 0.1)', iconColor: '#2dd4a8', borderColor: 'rgba(45, 212, 168, 0.3)', text: '#2dd4a8' },
        failed: { bg: 'rgba(224, 82, 82, 0.1)', iconColor: '#e05252', borderColor: 'rgba(224, 82, 82, 0.3)', text: '#e05252' },
        processing: { bg: 'rgba(212, 167, 45, 0.1)', iconColor: '#d4a72d', borderColor: 'rgba(212, 167, 45, 0.3)', text: '#d4a72d' },
    }

    // Default to completed styling since this page only shows completed
    const sc = statusColors[fData.status] || statusColors.completed

    const downloadMenuItems = [
        { key: 'header', type: 'group', label: <Text style={{ color: '#8888a8', fontSize: 12 }}>Choose format</Text> },
        { type: 'divider' },
        ...DOWNLOAD_FORMATS.map((fmt) => ({
            key: fmt.ext,
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
            {/* Header row */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: 12 }}>
                {/* Icon */}
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

                {/* Info */}
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
                        <StatChip icon={Clock} label={formatTime(file.audioDurationSec || 0)} />
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

                {/* Actions */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                    <Button
                        type="text"
                        size="small"
                        icon={<Eye size={14} />}
                        onClick={() => setExpanded(!expanded)}
                        style={{ color: expanded ? '#2dd4a8' : '#8888a8' }}
                        disabled={segments.length === 0}
                    >
                        {expanded ? "Hide" : "View"}
                    </Button>

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

            {/* Expanded: transcript viewer */}
            {expanded && segments.length > 0 && (
                <div style={{ borderTop: '1px solid #3a3a5c' }}>
                    {/* Toolbar */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'rgba(42, 42, 72, 0.2)' }}>
                        <Text style={{ fontSize: 12, color: '#8888a8' }}>
                            {segments.length} segments
                        </Text>
                        <Button
                            type="text"
                            size="small"
                            icon={copiedId === "all" ? <Check size={12} color="#2dd4a8" /> : <Copy size={12} />}
                            onClick={handleCopyAll}
                            style={{ fontSize: 12 }}
                        >
                            {copiedId === "all" ? "Copied!" : "Copy All"}
                        </Button>
                    </div>

                    {/* Segments */}
                    <div style={{ maxHeight: 384, overflowY: 'auto' }}>
                        {segments.map((seg, idx) => (
                            <div
                                key={idx}
                                style={{
                                    display: 'flex',
                                    gap: 12,
                                    padding: '10px 12px',
                                    borderBottom: '1px solid rgba(58, 58, 92, 0.5)',
                                    transition: 'background 0.2s',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(42, 42, 72, 0.2)' }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                            >
                                {/* Timestamp */}
                                <span style={{
                                    flexShrink: 0,
                                    borderRadius: 4,
                                    background: 'rgba(42, 42, 72, 0.6)',
                                    padding: '2px 6px',
                                    fontFamily: 'monospace',
                                    fontSize: 11,
                                    color: '#8888a8',
                                    height: 'fit-content',
                                    marginTop: 2,
                                }}>
                                    {formatTime(seg.start || 0)}
                                </span>

                                {/* Content */}
                                <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
                                    <span style={{ fontSize: 12, fontWeight: 500, color: '#2dd4a8', width: 'fit-content' }}>
                                        {seg.speaker ? `Speaker ${seg.speaker}` : "Speaker"}
                                    </span>
                                    <p style={{ fontSize: 13, lineHeight: 1.6, color: 'rgba(232, 232, 232, 0.9)', margin: 0 }}>{seg.text}</p>
                                </div>

                                {/* Copy */}
                                <Button
                                    type="text"
                                    size="small"
                                    icon={copiedId === idx ? <Check size={12} color="#2dd4a8" /> : <Copy size={12} />}
                                    onClick={() => handleCopy(idx, `[${formatTime(seg.start || 0)}] ${seg.speaker || "Speaker"}: ${seg.text}`)}
                                    style={{ flexShrink: 0, opacity: 0.5 }}
                                    onMouseEnter={(e) => { e.currentTarget.style.opacity = '1' }}
                                    onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.5' }}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            )}
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
