import { Select, Switch, Slider, Typography, Input } from "antd"
import { Languages, Users, Clock, MessageSquareText, ChevronDown, CopyCheck } from "lucide-react"
import { useState } from "react"

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



export function GlobalDefaults({ config, onChange, onApplyAll, fileCount = 0 }) {
    const [promptOpen, setPromptOpen] = useState(false)
    const [applyFlash, setApplyFlash] = useState(false)

    const update = (partial) => {
        onChange({ ...config, ...partial })
    }

    return (
        <div style={{ borderRadius: 8, border: '1px solid #3a3a5c', background: '#1e1e3a' }}>
            {/* Primary controls row - always visible */}
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '12px 16px', padding: 12 }}>
                {/* Language */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <Text style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#8888a8' }}>
                        <Languages size={12} /> Language
                    </Text>
                    <Select
                        value={config.language}
                        onChange={(v) => update({ language: v })}
                        options={languages}
                        style={{ width: 160 }}
                        size="small"
                    />
                </div>

                {/* Divider */}
                <div style={{ height: 32, width: 1, background: '#3a3a5c', alignSelf: 'flex-end' }} />

                {/* Multi-Speaker */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <Text style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#8888a8' }}>
                        <Users size={12} /> Multi-Speaker
                    </Text>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 32 }}>
                        <Switch
                            size="small"
                            checked={config.isMultiSpeaker}
                            onChange={(v) => update({ isMultiSpeaker: v })}
                        />
                        {config.isMultiSpeaker && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <Slider
                                    min={2}
                                    max={10}
                                    step={1}
                                    value={config.speakerCount}
                                    onChange={(v) => update({ speakerCount: v })}
                                    style={{ width: 80, margin: 0 }}
                                />
                                <Text strong style={{ fontSize: 12, color: '#2dd4a8', width: 12, textAlign: 'center' }}>
                                    {config.speakerCount}
                                </Text>
                            </div>
                        )}
                    </div>
                </div>

                {/* Divider */}
                <div style={{ height: 32, width: 1, background: '#3a3a5c', alignSelf: 'flex-end' }} />

                {/* Timestamps */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <Text style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#8888a8' }}>
                        <Clock size={12} /> Timestamps
                    </Text>
                    <div style={{ display: 'flex', alignItems: 'center', height: 32 }}>
                        <Switch
                            size="small"
                            checked={config.includeTimestamps}
                            onChange={(v) => update({ includeTimestamps: v })}
                        />
                    </div>
                </div>

                {/* Divider */}
                <div style={{ height: 32, width: 1, background: '#3a3a5c', alignSelf: 'flex-end' }} />

                {/* Prompt toggle */}
                <div style={{ alignSelf: 'flex-end' }}>
                    <button
                        type="button"
                        onClick={() => setPromptOpen(!promptOpen)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                            height: 32,
                            padding: '0 10px',
                            borderRadius: 6,
                            fontSize: 12,
                            color: '#8888a8',
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(42, 42, 72, 0.5)' }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                    >
                        <MessageSquareText size={12} />
                        Prompt
                        {config.prompt.length > 0 && (
                            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#2dd4a8' }} />
                        )}
                        <ChevronDown
                            size={12}
                            style={{ transition: 'transform 0.2s', transform: promptOpen ? 'rotate(180deg)' : undefined }}
                        />
                    </button>
                </div>

                {/* Spacer */}
                <div style={{ flex: 1 }} />

                {/* Apply All button */}
                {fileCount > 0 && onApplyAll && (
                    <div style={{ alignSelf: 'flex-end' }}>
                        <button
                            type="button"
                            onClick={() => {
                                onApplyAll()
                                setApplyFlash(true)
                                setTimeout(() => setApplyFlash(false), 1200)
                            }}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 6,
                                height: 32,
                                padding: '0 12px',
                                borderRadius: 6,
                                fontSize: 12,
                                fontWeight: 500,
                                color: '#2dd4a8',
                                background: applyFlash ? 'rgba(45, 212, 168, 0.2)' : 'rgba(45, 212, 168, 0.1)',
                                border: 'none',
                                cursor: 'pointer',
                                transition: 'background 0.2s',
                            }}
                        >
                            <CopyCheck size={12} />
                            {applyFlash ? "Applied!" : `Apply to All (${fileCount})`}
                        </button>
                    </div>
                )}
            </div>

            {/* Prompt area - toggled below the row */}
            {promptOpen && (
                <div style={{ borderTop: '1px solid #3a3a5c', padding: '8px 12px 12px' }}>
                    <TextArea
                        value={config.prompt}
                        onChange={(e) => update({ prompt: e.target.value })}
                        placeholder="Enter shared instructions for all files, e.g. 'Audio contains medical terminology' or 'Focus on speaker names and dates'..."
                        autoSize={{ minRows: 2 }}
                        style={{ fontSize: 12 }}
                    />
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                        <Text style={{ fontSize: 10, color: '#8888a8' }}>
                            This prompt will be sent with every transcription request
                        </Text>
                        <Text style={{ fontSize: 10, color: '#8888a8', fontVariantNumeric: 'tabular-nums' }}>
                            {config.prompt.length} / 2000
                        </Text>
                    </div>
                </div>
            )}
        </div>
    )
}
