// @ts-nocheck
import { useState, useEffect, useCallback } from "react"
import { Card, Button, Input, Select, Switch, Typography, Row, Col, Spin, Divider, Progress, Alert } from "antd"
import { Key, Bell, Save, Trash2, Cpu, Download, CheckCircle2 } from "lucide-react"
import { useModelManager } from "../components/ModelManager"
import { ReasonText } from "../components/disabled-reason"
import { PROVIDER_LIST_FAILED, useProviderList } from "../hooks/useProviderList"
import { modelForProvider, modelOptions, providerOptions, providerPromptDisabledReason, requiresApiKey } from "../utils/providerList"
import { api } from "../services/api"

const { Text } = Typography
const { TextArea } = Input

export default function SettingsPage() {
    const { getProviderConfig, saveProviderConfig, handleTestProvider } = useModelManager()
    const { providerList, failed: providerListFailed, reload: reloadProviderList } = useProviderList()

    const [providerForms, setProviderForms] = useState({})
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!providerList) return
        const loadConfigs = async () => {
            setLoading(true)
            const entries = await Promise.all(
                providerOptions(providerList).map(async ({ value: provider }) => {
                    try {
                        const config = await getProviderConfig(provider)
                        return [provider, {
                            apiKeys: config?.apiKeys?.length > 0 ? config.apiKeys : [""],
                            // 存的模型不屬於這個供應商（或已經不在清單上）時顯示預設模型
                            model: modelForProvider(providerList, provider, config?.model),
                            prompt: config?.prompt || "",
                            isDirty: false
                        }]
                    } catch (err) {
                        console.error(`Failed to load config for ${provider}:`, err)
                        return [provider, {
                            apiKeys: [""],
                            model: modelForProvider(providerList, provider, null),
                            prompt: "",
                            isDirty: false
                        }]
                    }
                })
            )
            setProviderForms(Object.fromEntries(entries))
            setLoading(false)
        }
        loadConfigs()
    }, [providerList, getProviderConfig])

    const updateForm = (provider, field, value) => {
        setProviderForms(prev => ({
            ...prev,
            [provider]: {
                ...prev[provider],
                [field]: value,
                isDirty: true
            }
        }))
    }

    const handleSave = async (provider) => {
        const form = providerForms[provider]
        const validApiKeys = form.apiKeys.filter(k => k.trim() !== "")

        const saved = await saveProviderConfig(provider, {
            apiKeys: validApiKeys,
            model: form.model,
            prompt: form.prompt
        })

        if (saved) {
            // 表單改顯示後端回傳的遮罩值，剛輸入的明文金鑰不留在畫面狀態裡
            const savedKeys = saved.apiKeys ?? []
            setProviderForms(prev => ({
                ...prev,
                [provider]: { ...form, isDirty: false, apiKeys: savedKeys.length > 0 ? savedKeys : [""] }
            }))
        }
    }

    if (loading && !providerListFailed) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', minHeight: 400 }}>
                <Spin size="large" />
            </div>
        )
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
            {providerListFailed && (
                <Alert
                    type="error"
                    showIcon
                    message={PROVIDER_LIST_FAILED}
                    action={<Button size="small" onClick={reloadProviderList}>重試</Button>}
                />
            )}
            <Row gutter={[24, 24]}>
                {!providerListFailed && providerOptions(providerList).map(({ value: provider, label }) => (
                    <Col xs={24} lg={12} key={provider}>
                        <Card
                            title={
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <Key size={16} color="#2dd4a8" />
                                        <span style={{ color: '#e8e8e8' }}>{label}</span>
                                    </div>
                                    {providerForms[provider].isDirty && (
                                        <Text style={{ fontSize: 12, color: '#d4a72d' }}>Unsaved changes</Text>
                                    )}
                                </div>
                            }
                            style={{
                                border: providerForms[provider].isDirty ? '1px solid rgba(212, 167, 45, 0.4)' : '1px solid #3a3a5c',
                                transition: 'border-color 0.3s'
                            }}
                        >
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                                {/* 只有要使用者金鑰的供應商才有金鑰欄位（照供應商清單，本機不用） */}
                                {requiresApiKey(providerList, provider) && <div>
                                    <Text style={{ color: '#e8e8e8', fontSize: 13, display: 'block', marginBottom: 6 }}>API Keys (Try from top to bottom)</Text>
                                    {providerForms[provider].apiKeys.map((key, idx) => (
                                        <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                                            <Input.Password
                                                value={key}
                                                onChange={(e) => {
                                                    const newKeys = [...providerForms[provider].apiKeys]
                                                    newKeys[idx] = e.target.value
                                                    updateForm(provider, 'apiKeys', newKeys)
                                                }}
                                                placeholder={`API Key ${idx + 1}`}
                                                style={{ flex: 1, fontFamily: 'monospace' }}
                                            />
                                            {providerForms[provider].apiKeys.length > 1 && (
                                                <Button
                                                    danger
                                                    icon={<Trash2 size={14} />}
                                                    onClick={() => {
                                                        const newKeys = providerForms[provider].apiKeys.filter((_, i) => i !== idx)
                                                        updateForm(provider, 'apiKeys', newKeys)
                                                    }}
                                                />
                                            )}
                                        </div>
                                    ))}
                                    <Button
                                        type="dashed"
                                        onClick={() => updateForm(provider, 'apiKeys', [...providerForms[provider].apiKeys, ""])}
                                        style={{ width: '100%', marginTop: 4 }}
                                    >
                                        + Add API Key
                                    </Button>
                                </div>}

                                <div>
                                    <Text style={{ color: '#e8e8e8', fontSize: 13, display: 'block', marginBottom: 6 }}>Default Model</Text>
                                    <Select
                                        value={providerForms[provider].model}
                                        onChange={(v) => updateForm(provider, 'model', v)}
                                        style={{ width: '100%' }}
                                        options={modelOptions(providerList, provider)}
                                    />
                                </div>

                                <PromptTemplateField
                                    value={providerForms[provider].prompt}
                                    onChange={(value) => updateForm(provider, 'prompt', value)}
                                    disabledReason={providerPromptDisabledReason(providerList, provider)}
                                />

                                <Divider style={{ borderColor: '#3a3a5c', margin: '4px 0' }} />

                                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                                    {/* 測畫面上選的模型：本機要查的是這個模型的權重 */}
                                    <Button onClick={() => handleTestProvider(provider, providerForms[provider].model)}>
                                        Test Connection
                                    </Button>
                                    <Button
                                        type={providerForms[provider].isDirty ? "primary" : "default"}
                                        icon={<Save size={16} />}
                                        onClick={() => handleSave(provider)}
                                        disabled={!providerForms[provider].isDirty}
                                    >
                                        Save
                                    </Button>
                                </div>
                            </div>
                        </Card>
                    </Col>
                ))}

                <LocalModelsCard />

                <Col xs={24} lg={12}>
                    <Card
                        title={
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <Bell size={16} color="#2dd4a8" />
                                <span style={{ color: '#e8e8e8' }}>Notifications (Coming Soon)</span>
                            </div>
                        }
                        style={{ border: '1px solid #3a3a5c', height: '100%' }}
                    >
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, opacity: 0.5, pointerEvents: 'none' }}>
                            <SettingToggle label="Transcription Complete" desc="Notify when a job finishes" defaultChecked />
                            <SettingToggle label="Transcription Failed" desc="Alert on job failures" defaultChecked />
                            <SettingToggle label="Quota Warning" desc="Alert when nearing usage limits" defaultChecked />
                            <SettingToggle label="Weekly Usage Report" desc="Weekly summary via email" />
                        </div>
                    </Card>
                </Col>

            </Row>
        </div>
    )
}

/**
 * 免安裝模式（standalone）的本機模型權重管理卡片。
 * Docker 模式下 status.standalone 為 false，整張卡不渲染。
 */
function LocalModelsCard() {
    const [status, setStatus] = useState(null)
    const [starting, setStarting] = useState(false)
    const [startError, setStartError] = useState(null)

    const refresh = useCallback(async () => {
        try {
            setStatus(await api.localModels.status())
        } catch {
            /* 後端未支援此端點（舊版）時整卡隱藏 */
        }
    }, [])

    useEffect(() => { refresh() }, [refresh])

    // 下載進行中每 2 秒輪詢進度
    const downloading = status?.download?.state === 'downloading'
    useEffect(() => {
        if (!downloading) return
        const timer = setInterval(refresh, 2000)
        return () => clearInterval(timer)
    }, [downloading, refresh])

    if (!status?.standalone) return null

    const dl = status.download
    // model 省略＝預設模型（MOSS）所需；'all'＝連同選用模型（Qwen3-ASR、VibeVoice）
    const handleDownload = async (model) => {
        setStarting(true)
        setStartError(null)
        try {
            await api.localModels.download(model)
            await refresh()
        } catch (err) {
            setStartError(err.message)
        } finally {
            setStarting(false)
        }
    }

    return (
        <Col xs={24} lg={12}>
            <Card
                title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Cpu size={16} color="#2dd4a8" />
                        <span style={{ color: '#e8e8e8' }}>Local Models (本機 GPU 模型)</span>
                    </div>
                }
                style={{ border: '1px solid #3a3a5c', height: '100%' }}
            >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <Text style={{ color: status.gpu_available ? '#2dd4a8' : '#d46a2d', fontSize: 13 }}>
                        {status.gpu_available
                            ? `GPU: ${status.gpu_name}`
                            : '未偵測到 NVIDIA GPU — 本機轉錄不可用（Gemini 不受影響）'}
                    </Text>

                    {status.models.map(m => (
                        <div key={m.repo_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Text style={{ color: '#8888a8', fontSize: 12, fontFamily: 'monospace' }}>
                                {m.repo_id}{m.required ? '' : '（選用）'}
                            </Text>
                            {m.downloaded
                                ? <CheckCircle2 size={14} color="#2dd4a8" />
                                : <Text style={{ color: m.required ? '#d4a72d' : '#8888a8', fontSize: 12 }}>未下載</Text>}
                        </div>
                    ))}

                    {downloading && (
                        <div>
                            <Text style={{ color: '#e8e8e8', fontSize: 12, display: 'block', marginBottom: 4 }}>
                                下載中 ({dl.repo_index}/{dl.repo_count}): {dl.current_repo}
                            </Text>
                            <Progress
                                percent={dl.progress_pct ?? 0}
                                status="active"
                                strokeColor="#2dd4a8"
                            />
                        </div>
                    )}

                    {dl.state === 'failed' && (
                        <Alert
                            type="error"
                            showIcon
                            message="下載中斷"
                            description={`${dl.error || '未知錯誤'} — 已下載部分會保留，重新下載即續傳。`}
                        />
                    )}
                    {startError && (
                        <Alert type="error" showIcon message={startError} />
                    )}

                    {!status.all_downloaded && !downloading && (
                        <Button
                            type="primary"
                            icon={<Download size={16} />}
                            loading={starting}
                            onClick={() => handleDownload()}
                            disabled={!status.gpu_available}
                        >
                            {dl.state === 'failed' && dl.target !== 'all' ? '重試下載' : `下載模型權重 (~${status.required_size_gb} GB)`}
                        </Button>
                    )}
                    {status.all_downloaded && !status.optional_downloaded && !downloading && (
                        <Button
                            icon={<Download size={16} />}
                            loading={starting}
                            onClick={() => handleDownload('all')}
                            disabled={!status.gpu_available}
                        >
                            {dl.state === 'failed' && dl.target === 'all' ? '重試下載選用模型' : `下載選用模型 (~${status.optional_size_gb} GB)`}
                        </Button>
                    )}

                    <Text style={{ color: '#8888a8', fontSize: 12 }}>
                        權重存放於 {status.hf_home}；首次使用 Local provider 前需完成下載。
                        預設的 MOSS 只需非選用的兩項；選用權重供「MOSS + Qwen3-ASR」與舊版「VibeVoice + Qwen3-ASR」使用。
                    </Text>
                </div>
            </Card>
        </Col>
    )
}

/**
 * 供應商的提示詞範本；這個供應商的模型都不支援提示詞時停用並顯示原因。範本整份取代系統內建的，
 * 打了字就看不到 placeholder，所以欄位下方的說明一直顯示（#196）。
 */
function PromptTemplateField({ value, onChange, disabledReason }) {
    return (
        <div>
            <Text style={{ color: '#e8e8e8', fontSize: 13, display: 'block', marginBottom: 6 }}>Prompt Template</Text>
            <TextArea
                value={value}
                onChange={(e) => onChange(e.target.value)}
                disabled={Boolean(disabledReason)}
                placeholder="Empty: the built-in template is used. Anything saved here replaces the whole prompt sent for every file, so keep the instructions that ask for LRC format and timestamps..."
                rows={4}
            />
            <Text style={{ display: 'block', color: '#8888a8', fontSize: 12, marginTop: 4 }}>
                The whole prompt sent for every file with this provider. Keep the instructions that ask for LRC format and timestamps, or transcription fails.
                Leave it empty to use the built-in template. To add a line such as speaker names or terms to keep as written, use the prompt on New Transcription instead.
            </Text>
            <ReasonText reason={disabledReason} style={{ display: 'block', fontSize: 12, marginTop: 4 }} />
        </div>
    )
}

function SettingToggle({ label, desc, defaultChecked }) {
    return (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
                <Text style={{ color: '#e8e8e8', fontSize: 13 }}>{label}</Text>
                <Text style={{ display: 'block', color: '#8888a8', fontSize: 12 }}>{desc}</Text>
            </div>
            <Switch defaultChecked={defaultChecked} />
        </div>
    )
}
