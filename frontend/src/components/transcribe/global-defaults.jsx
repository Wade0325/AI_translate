// @ts-nocheck
import { Select, Switch, Typography, Input, Tooltip } from "antd"
import { Languages, Users, MessageSquareText, ChevronDown, CopyCheck } from "lucide-react"
import { useState } from "react"
import { ReasonText } from "@/components/disabled-reason"
import { languages } from "@/constants/languages"

const { Text } = Typography
const { TextArea } = Input

/**
 * promptDisabledReason：所選的模型不支援提示詞時的原因；有值時提示詞欄位停用並顯示它。
 */
export function GlobalDefaults({ config, onChange, onApplyAll, fileCount = 0, promptDisabledReason = null }) {
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
                            aria-label="Multi-Speaker"
                            checked={config.isMultiSpeaker}
                            onChange={(v) => update({ isMultiSpeaker: v })}
                        />
                    </div>
                </div>

                {/* Divider */}
                <div style={{ height: 32, width: 1, background: '#3a3a5c', alignSelf: 'flex-end' }} />

                {/* Prompt toggle：所選的模型不支援提示詞時仍可展開，看得到停用的欄位與原因 */}
                <div style={{ alignSelf: 'flex-end' }}>
                    <Tooltip title={promptDisabledReason}>
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
                                color: promptDisabledReason ? '#686888' : '#8888a8',
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
                                <span style={{
                                    width: 6,
                                    height: 6,
                                    borderRadius: '50%',
                                    background: promptDisabledReason ? '#686888' : '#2dd4a8',
                                }} />
                            )}
                            <ChevronDown
                                size={12}
                                style={{ transition: 'transform 0.2s', transform: promptOpen ? 'rotate(180deg)' : undefined }}
                            />
                        </button>
                    </Tooltip>
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
                        disabled={Boolean(promptDisabledReason)}
                        placeholder="Added after the prompt template for every file that has no prompt of its own, e.g. speaker names or terms to keep as written. To rewrite the whole prompt, edit the prompt template in Settings..."
                        autoSize={{ minRows: 2 }}
                        style={{ fontSize: 12 }}
                    />
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                        {promptDisabledReason ? (
                            <ReasonText reason={promptDisabledReason} />
                        ) : (
                            <Text style={{ fontSize: 10, color: '#8888a8' }}>
                                Added after the prompt template for every file that has no prompt of its own. The template's LRC and timestamp instructions are kept.
                            </Text>
                        )}
                        <Text style={{ fontSize: 10, color: '#8888a8', fontVariantNumeric: 'tabular-nums' }}>
                            {config.prompt.length} / 2000
                        </Text>
                    </div>
                </div>
            )}
        </div>
    )
}
