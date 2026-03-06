import { useState } from "react"
import {
    FileAudio,
    X,
    Settings2,
    Languages,
    Users,
    MessageSquareText,
    Clock,
    RotateCcw,
    Download,
    Eye,
    FileText,
    ChevronDown,
    Loader2,
    CheckCircle2,
    AlertCircle,
    Hourglass,
} from "lucide-react"
import { Button, Select, Switch, Slider, Tag, Typography, Input, Dropdown, Spin, Space, Tooltip } from "antd"
import { LoadingOutlined } from "@ant-design/icons"

const { Text } = Typography
const { TextArea } = Input

const languages = [
    {
        label: "Common",
        options: [
            { value: "auto", label: "Auto Detect" },
            { value: "zh-TW", label: "Chinese (Traditional)" },
            { value: "zh-CN", label: "Chinese (Simplified)" },
            { value: "en", label: "English" },
            { value: "ja", label: "Japanese" },
            { value: "ko", label: "Korean" },
        ],
    },
    {
        label: "European",
        options: [
            { value: "fr", label: "French" },
            { value: "de", label: "German" },
            { value: "es", label: "Spanish" },
            { value: "pt", label: "Portuguese" },
            { value: "it", label: "Italian" },
            { value: "nl", label: "Dutch" },
            { value: "ru", label: "Russian" },
        ],
    },
    {
        label: "Other",
        options: [
            { value: "ar", label: "Arabic" },
            { value: "hi", label: "Hindi" },
            { value: "th", label: "Thai" },
            { value: "vi", label: "Vietnamese" },
            { value: "id", label: "Indonesian" },
        ],
    },
]

function formatLang(value) {
    for (const g of languages) {
        for (const item of g.options) {
            if (item.value === value) return item.label
        }
    }
    return value
}

const statusConfig = {
    waiting: { icon: Hourglass, color: "#8888a8", label: "等待處理" },
    processing: { icon: Loader2, color: "#d4a72d", label: "處理中" },
    completed: { icon: CheckCircle2, color: "#2dd4a8", label: "完成" },
    error: { icon: AlertCircle, color: "#e05252", label: "錯誤" },
    batch_pending: { icon: Hourglass, color: "#47b8d4", label: "批次等待" },
}

const downloadFormats = [
    { key: "lrc", label: "LRC" },
    { key: "srt", label: "SRT" },
    { key: "vtt", label: "VTT" },
    { key: "txt", label: "TXT" },
]

export function FileConfigCard({
    config,
    globalConfig,
    onUpdate,
    onRemove,
    onPreview,
    onDownload,
    onReprocess,
    onAttachText,
    onAttachTextFromFile,
    readOnly = false,
}) {
    const [expanded, setExpanded] = useState(false)

    const update = (partial) => {
        onUpdate(config.id, { ...partial, hasOverride: true })
    }

    const resetToGlobal = () => {
        onUpdate(config.id, {
            language: globalConfig.language,
            isMultiSpeaker: globalConfig.isMultiSpeaker,
            speakerCount: globalConfig.speakerCount,
            prompt: globalConfig.prompt,
            includeTimestamps: globalConfig.includeTimestamps,
            hasOverride: false,
        })
        setExpanded(false)
    }

    const isOverridden = (field) => {
        if (!config.hasOverride) return false
        return config[field] !== globalConfig[field]
    }

    const sc = statusConfig[config.status] || statusConfig.waiting
    const StatusIcon = sc.icon
    const isCompleted = config.status === "completed"
    const isError = config.status === "error"
    const isActive = config.status === "processing"

    const tags = [
        { label: formatLang(config.language), icon: Languages, overridden: isOverridden("language") },
        { label: config.isMultiSpeaker ? `${config.speakerCount} speakers` : "Single", icon: Users, overridden: isOverridden("isMultiSpeaker") || isOverridden("speakerCount") },
        { label: config.includeTimestamps ? "Timestamps" : "No timestamps", icon: Clock, overridden: isOverridden("includeTimestamps") },
        ...((config.prompt ?? "").length > 0
            ? [{ label: "Prompt", icon: MessageSquareText, overridden: config.prompt !== globalConfig.prompt }]
            : []),
        ...(config.original_text
            ? [{ label: "附加文本", icon: FileText, overridden: true }]
            : []),
    ]

    return (
        <div style={{
            borderRadius: 8,
            border: isCompleted
                ? "1px solid rgba(45, 212, 168, 0.3)"
                : isError
                    ? "1px solid rgba(224, 82, 82, 0.3)"
                    : isActive
                        ? "1px solid rgba(212, 167, 45, 0.3)"
                        : config.hasOverride
                            ? "1px solid rgba(45, 212, 168, 0.3)"
                            : "1px solid #3a3a5c",
            background: "#1e1e3a",
            overflow: "hidden",
            transition: "border-color 0.2s",
        }}>
            {/* Collapsed header row */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px" }}>
                <div style={{
                    width: 32,
                    height: 32,
                    flexShrink: 0,
                    borderRadius: 6,
                    background: `${sc.color}1a`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                }}>
                    {isActive ? (
                        <Spin indicator={<LoadingOutlined style={{ fontSize: 14, color: sc.color }} spin />} />
                    ) : (
                        <StatusIcon size={14} color={sc.color} />
                    )}
                </div>

                <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Text ellipsis style={{ fontSize: 13, fontWeight: 500, color: "#e8e8e8", maxWidth: 300 }}>
                            {config.name}
                        </Text>
                        <Text style={{ fontSize: 11, color: "#8888a8", flexShrink: 0 }}>{config.size}</Text>
                        <Tag
                            style={{
                                fontSize: 10,
                                padding: "0 6px",
                                height: 16,
                                lineHeight: "16px",
                                borderColor: `${sc.color}4d`,
                                color: sc.color,
                                background: "transparent",
                                margin: 0,
                            }}
                        >
                            {config.statusText || sc.label}
                        </Tag>
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                        {tags.map((tag) => (
                            <Tag
                                key={tag.label}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: 4,
                                    fontSize: 10,
                                    padding: "1px 6px",
                                    borderRadius: 4,
                                    lineHeight: "16px",
                                    margin: 0,
                                    background: tag.overridden ? "rgba(45, 212, 168, 0.1)" : "rgba(42, 42, 72, 0.6)",
                                    border: tag.overridden ? "1px solid rgba(45, 212, 168, 0.2)" : "1px solid transparent",
                                    color: tag.overridden ? "#2dd4a8" : "#8888a8",
                                }}
                            >
                                <tag.icon size={10} />
                                {tag.label}
                            </Tag>
                        ))}
                        {/* Token/Cost stats for completed files */}
                        {isCompleted && config.tokens_used > 0 && (
                            <Text style={{ fontSize: 10, color: "#2dd4a8", marginLeft: 4 }}>
                                {config.tokens_used?.toLocaleString()} tokens · ${config.cost?.toFixed(4)}
                            </Text>
                        )}
                    </div>
                </div>

                {/* Action buttons */}
                <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
                    {/* Preview */}
                    {isCompleted && onPreview && (
                        <Tooltip title="預覽">
                            <Button
                                type="text"
                                size="small"
                                icon={<Eye size={14} />}
                                onClick={() => onPreview(config)}
                                style={{ width: 28, height: 28, color: "#8888a8" }}
                            />
                        </Tooltip>
                    )}
                    {/* Download */}
                    {isCompleted && onDownload && (
                        <Dropdown
                            menu={{
                                items: downloadFormats,
                                onClick: ({ key }) => {
                                    const content = config.result?.[key]
                                    if (content) onDownload(content, config.name, key)
                                },
                            }}
                        >
                            <Tooltip title="下載">
                                <Button
                                    type="text"
                                    size="small"
                                    icon={<Download size={14} />}
                                    style={{ width: 28, height: 28, color: "#8888a8" }}
                                />
                            </Tooltip>
                        </Dropdown>
                    )}
                    {/* Attach text */}
                    {!readOnly && !isCompleted && onAttachText && (
                        <Tooltip title="附加文本">
                            <Button
                                type="text"
                                size="small"
                                icon={<FileText size={14} />}
                                onClick={() => onAttachText(config.id)}
                                style={{ width: 28, height: 28, color: config.original_text ? "#2dd4a8" : "#8888a8" }}
                            />
                        </Tooltip>
                    )}
                    {/* Reprocess */}
                    {!readOnly && (isCompleted || isError) && onReprocess && (
                        <Tooltip title="重新處理">
                            <Button
                                type="text"
                                size="small"
                                icon={<RotateCcw size={14} />}
                                onClick={() => onReprocess(config.id)}
                                style={{ width: 28, height: 28, color: "#8888a8" }}
                            />
                        </Tooltip>
                    )}
                    {/* Settings */}
                    {!readOnly && (
                        <Button
                            type="text"
                            size="small"
                            icon={<Settings2 size={14} />}
                            onClick={() => setExpanded(!expanded)}
                            style={{
                                width: 28,
                                height: 28,
                                color: expanded ? "#2dd4a8" : config.hasOverride ? "#2dd4a8" : "#8888a8",
                                background: expanded ? "rgba(45, 212, 168, 0.1)" : "transparent",
                            }}
                        />
                    )}
                    {/* Remove */}
                    {!readOnly && (
                        <Button
                            type="text"
                            size="small"
                            icon={<X size={14} />}
                            onClick={() => onRemove(config.id)}
                            style={{ width: 28, height: 28, color: "#8888a8" }}
                            danger
                        />
                    )}
                </div>
            </div>

            {/* Expanded per-file override settings */}
            {expanded && (
                <div style={{ borderTop: "1px solid #3a3a5c", background: "rgba(20, 20, 40, 0.8)", padding: "12px 16px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                        <Text style={{ fontSize: 11, fontWeight: 500, color: "#8888a8", textTransform: "uppercase", letterSpacing: 1 }}>
                            Per-file overrides
                        </Text>
                        {config.hasOverride && (
                            <Button
                                type="text"
                                size="small"
                                icon={<RotateCcw size={12} />}
                                onClick={resetToGlobal}
                                style={{ fontSize: 11, color: "#8888a8", height: 24 }}
                            >
                                Reset to global
                            </Button>
                        )}
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
                        {/* Language */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <Text style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#8888a8" }}>
                                <Languages size={12} /> Language
                            </Text>
                            <Select
                                value={config.language}
                                onChange={(v) => update({ language: v })}
                                options={languages}
                                style={{ width: "100%" }}
                                size="small"
                            />
                        </div>

                        {/* Multi-Speaker */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <Text style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#8888a8" }}>
                                <Users size={12} /> Speakers
                            </Text>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, height: 32 }}>
                                <Switch
                                    size="small"
                                    checked={config.isMultiSpeaker}
                                    onChange={(v) => update({ isMultiSpeaker: v })}
                                />
                                {config.isMultiSpeaker && (
                                    <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1 }}>
                                        <Slider
                                            min={2}
                                            max={10}
                                            step={1}
                                            value={config.speakerCount}
                                            onChange={(v) => update({ speakerCount: v })}
                                            style={{ flex: 1, margin: 0 }}
                                        />
                                        <Text strong style={{ fontSize: 12, color: "#2dd4a8", width: 12, textAlign: "center" }}>
                                            {config.speakerCount}
                                        </Text>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Timestamps */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <Text style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#8888a8" }}>
                                <Clock size={12} /> Timestamps
                            </Text>
                            <div style={{ display: "flex", alignItems: "center", height: 32 }}>
                                <Switch
                                    size="small"
                                    checked={config.includeTimestamps}
                                    onChange={(v) => update({ includeTimestamps: v })}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Custom Prompt */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 12 }}>
                        <Text style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#8888a8" }}>
                            <MessageSquareText size={12} />
                            Custom Prompt
                            {config.prompt === globalConfig.prompt && (
                                <span style={{ fontSize: 10, color: "rgba(136, 136, 168, 0.5)", marginLeft: 4 }}>(same as global)</span>
                            )}
                        </Text>
                        <TextArea
                            value={config.prompt}
                            onChange={(e) => update({ prompt: e.target.value })}
                            placeholder="Override the global prompt for this file..."
                            autoSize={{ minRows: 2 }}
                            style={{ fontSize: 12 }}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
