import { useState } from "react"
import {
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
    Loader2,
    CheckCircle2,
    AlertCircle,
    Hourglass,
    Scissors,
    Ban,
} from "lucide-react"
import { Button, Select, Switch, Slider, Tag, Typography, Input, Dropdown, Spin, Tooltip, Popconfirm } from "antd"
import { LoadingOutlined } from "@ant-design/icons"
import { ReasonText, ReasonTooltip } from "@/components/disabled-reason"
import { languages, formatLang } from "@/constants/languages"
import { downloadFormats } from "@/constants/downloadFormats"
import { globalSettingsPatch } from "@/utils/transcribeRequest"

const { Text } = Typography
const { TextArea } = Input

const statusConfig = {
    waiting: { icon: Hourglass, color: "#8888a8", label: "等待處理" },
    processing: { icon: Loader2, color: "#d4a72d", label: "處理中" },
    completed: { icon: CheckCircle2, color: "#2dd4a8", label: "完成" },
    error: { icon: AlertCircle, color: "#e05252", label: "錯誤" },
    batch_pending: { icon: Hourglass, color: "#47b8d4", label: "批次等待" },
    cancelled: { icon: Ban, color: "#8888a8", label: "已取消" },
}

/**
 * disabledReasons：所選的模型不支援的輸入與原因（{ prompt, userText }，見 utils/providerList.js 的
 * disabledReasonsFor）；
 * 有原因的欄位停用並顯示它，已經填了的值標成不會送出。
 */
export function FileConfigCard({
    config,
    globalConfig,
    onUpdate,
    onRemove,
    onPreview,
    onDownload,
    onReprocess,
    onAttachText,
    onVadTest,
    onCancel,
    vadTesting = false,
    readOnly = false,
    disabledReasons = {},
}) {
    const [expanded, setExpanded] = useState(false)

    const update = (partial) => {
        onUpdate(config.id, { ...partial, hasOverride: true })
    }

    const resetToGlobal = () => {
        onUpdate(config.id, globalSettingsPatch(globalConfig))
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
    const isCancelled = config.status === "cancelled"

    // 還會送出的檔案（等待中、失敗、已取消）才標出所選的模型不支援、送出時不會帶上的輸入；
    // notSentReason 是不會帶上的原因，會帶上時是 null
    const submittable = ["waiting", "error", "cancelled"].includes(config.status)
    const notSentReason = (reason) => (submittable ? reason : null)

    const tags = [
        { label: formatLang(config.language), icon: Languages, overridden: isOverridden("language") },
        { label: config.isMultiSpeaker ? `${config.speakerCount} speakers` : "Single", icon: Users, overridden: isOverridden("isMultiSpeaker") || isOverridden("speakerCount") },
        { label: config.includeTimestamps ? "Timestamps" : "No timestamps", icon: Clock, overridden: isOverridden("includeTimestamps") },
        ...((config.prompt ?? "").length > 0
            ? [{
                label: "Prompt",
                icon: MessageSquareText,
                overridden: config.prompt !== globalConfig.prompt,
                notSentReason: notSentReason(disabledReasons.prompt),
            }]
            : []),
        ...(config.original_text
            ? [{
                label: "使用者文稿",
                icon: FileText,
                overridden: true,
                notSentReason: notSentReason(disabledReasons.userText),
            }]
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
                        {tags.map((tag) => {
                            const highlighted = tag.overridden && !tag.notSentReason
                            return (
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
                                        background: highlighted ? "rgba(45, 212, 168, 0.1)" : "rgba(42, 42, 72, 0.6)",
                                        border: highlighted ? "1px solid rgba(45, 212, 168, 0.2)" : "1px solid transparent",
                                        color: highlighted ? "#2dd4a8" : "#8888a8",
                                        textDecoration: tag.notSentReason ? "line-through" : undefined,
                                    }}
                                >
                                    <tag.icon size={10} />
                                    {tag.label}
                                </Tag>
                            )
                        })}
                        {isCompleted && config.tokens_used > 0 && (
                            <Text style={{ fontSize: 10, color: "#2dd4a8", marginLeft: 4 }}>
                                {config.tokens_used?.toLocaleString()} tokens · ${config.cost?.toFixed(4)}
                            </Text>
                        )}
                    </div>
                    {/* 劃掉的輸入不會送出，原因直接寫出來 */}
                    {tags.filter((tag) => tag.notSentReason).map((tag) => (
                        <ReasonText key={tag.label} reason={tag.notSentReason} />
                    ))}
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
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
                    {/* VAD 切割測試：僅等待中的本機音訊 */}
                    {!readOnly && !isCompleted && !isActive && onVadTest && (
                        <Tooltip title="VAD 切割測試（不轉錄）">
                            <Button
                                type="text"
                                size="small"
                                loading={vadTesting}
                                icon={<Scissors size={14} />}
                                onClick={() => onVadTest(config.id)}
                                style={{ width: 28, height: 28, color: "#47b8d4" }}
                            />
                        </Tooltip>
                    )}
                    {/* 使用者文稿：處理中時隱藏；所選的模型不支援使用者文稿時停用並說明原因 */}
                    {!readOnly && !isCompleted && !isActive && onAttachText && (
                        <ReasonTooltip title={disabledReasons.userText || "附加使用者文稿"}>
                            <Button
                                type="text"
                                size="small"
                                icon={<FileText size={14} />}
                                disabled={Boolean(disabledReasons.userText)}
                                onClick={() => onAttachText(config.id)}
                                style={{
                                    width: 28,
                                    height: 28,
                                    color: config.original_text && !disabledReasons.userText ? "#2dd4a8" : "#8888a8",
                                }}
                            />
                        </ReasonTooltip>
                    )}
                    {/* Cancel：僅執行中且由單檔轉錄啟動的任務 */}
                    {!readOnly && isActive && onCancel && (
                        <Popconfirm
                            title="確定取消此任務？"
                            description="已取消的任務可重新處理"
                            onConfirm={() => onCancel(config.id)}
                            okText="確定"
                            cancelText="返回"
                            placement="topRight"
                        >
                            <Tooltip title="取消任務">
                                <Button
                                    type="text"
                                    size="small"
                                    icon={<Ban size={14} />}
                                    style={{ width: 28, height: 28, color: "#e05252" }}
                                />
                            </Tooltip>
                        </Popconfirm>
                    )}
                    {!readOnly && (isCompleted || isError || isCancelled) && onReprocess && (
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
                    {/* Settings：處理中時隱藏 */}
                    {!readOnly && !isActive && (
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

            {/* Expanded per-file override settings：處理中時強制收起 */}
            {expanded && !isActive && (
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
                            disabled={Boolean(disabledReasons.prompt)}
                            placeholder="Override the global prompt for this file..."
                            autoSize={{ minRows: 2 }}
                            style={{ fontSize: 12 }}
                        />
                        <ReasonText reason={disabledReasons.prompt} />
                    </div>
                </div>
            )}
        </div>
    )
}
