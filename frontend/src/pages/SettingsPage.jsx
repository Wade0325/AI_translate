import { useState, useEffect } from "react"
import { Card, Button, Input, Select, Switch, Typography, Row, Col, Spin, message, Space, Popconfirm, Divider } from "antd"
import { Key, Globe, Bell, Save, Trash2, Edit } from "lucide-react"
import { useModelManager } from "../components/ModelManager"
import { modelOptions } from "../constants/modelConfig"

const { Title, Text } = Typography
const { TextArea } = Input

export default function SettingsPage() {
    const { getProviderConfig, saveProviderConfig, handleTestProvider } = useModelManager()

    // We'll manage settings locally before saving
    const [providerForms, setProviderForms] = useState({})
    const [loading, setLoading] = useState(true)

    // Load configs for all providers on mount
    useEffect(() => {
        const loadConfigs = async () => {
            setLoading(true)
            const forms = {}
            for (const provider of Object.keys(modelOptions)) {
                try {
                    const config = await getProviderConfig(provider)
                    forms[provider] = {
                        apiKeys: config?.apiKeys?.length > 0 ? config.apiKeys : [""],
                        model: config?.model || modelOptions[provider][0].value,
                        prompt: config?.prompt || "",
                        isDirty: false
                    }
                } catch (err) {
                    console.error(`Failed to load config for ${provider}:`, err)
                    forms[provider] = {
                        apiKeys: [""],
                        model: modelOptions[provider][0].value,
                        prompt: "",
                        isDirty: false
                    }
                }
            }
            setProviderForms(forms)
            setLoading(false)
        }
        loadConfigs()
    }, [getProviderConfig])

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

        const success = await saveProviderConfig(provider, {
            apiKeys: validApiKeys,
            model: form.model,
            prompt: form.prompt
        })

        if (success) {
            setProviderForms(prev => ({
                ...prev,
                [provider]: { ...form, isDirty: false, apiKeys: validApiKeys.length > 0 ? validApiKeys : [""] }
            }))
        }
    }

    if (loading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', minHeight: 400 }}>
                <Spin size="large" />
            </div>
        )
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
            <Row gutter={[24, 24]}>
                {/* Provider Configurations */}
                {Object.keys(modelOptions).map(provider => (
                    <Col xs={24} lg={12} key={provider}>
                        <Card
                            title={
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <Key size={16} color="#2dd4a8" />
                                        <span style={{ color: '#e8e8e8' }}>{provider} Configuration</span>
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
                                {/* API Keys */}
                                <div>
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
                                </div>

                                {/* Default Model */}
                                <div>
                                    <Text style={{ color: '#e8e8e8', fontSize: 13, display: 'block', marginBottom: 6 }}>Default Model</Text>
                                    <Select
                                        value={providerForms[provider].model}
                                        onChange={(v) => updateForm(provider, 'model', v)}
                                        style={{ width: '100%' }}
                                        options={modelOptions[provider]}
                                    />
                                </div>

                                {/* System Prompt Template */}
                                <div>
                                    <Text style={{ color: '#e8e8e8', fontSize: 13, display: 'block', marginBottom: 6 }}>Global Prompt Template</Text>
                                    <TextArea
                                        value={providerForms[provider].prompt}
                                        onChange={(e) => updateForm(provider, 'prompt', e.target.value)}
                                        placeholder="System level instructions or prompts to guide the model..."
                                        rows={4}
                                    />
                                </div>

                                <Divider style={{ borderColor: '#3a3a5c', margin: '4px 0' }} />

                                {/* Actions */}
                                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                                    <Button onClick={() => handleTestProvider(provider)}>
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

                {/* Notifications Placeholder (UI Only) */}
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
