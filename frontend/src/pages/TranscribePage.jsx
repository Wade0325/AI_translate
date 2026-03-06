import { useState, useRef } from "react"
import { Card, Typography, Button, Input, Modal, Pagination, Space, Tag, Dropdown, Popconfirm, message } from "antd"
import { UploadZone } from "@/components/transcribe/upload-zone"
import { GlobalDefaults } from "@/components/transcribe/global-defaults"
import { FileConfigCard } from "@/components/transcribe/file-config-card"
import { CostEstimator } from "@/components/transcribe/cost-estimator"
import { useTranscription } from "@/context/TranscriptionContext"
import { useModelManager } from "@/components/ModelManager"
import { modelOptions, findProviderForModel } from "@/constants/modelConfig"
import {
    LinkOutlined,
    FileTextOutlined,
    HistoryOutlined,
    DownloadOutlined,
    EyeOutlined,
} from "@ant-design/icons"
import { AlertCircle, Youtube } from "lucide-react"

const { Text, Title } = Typography
const { TextArea } = Input

const PAGE_SIZE = 5

export default function TranscribePage() {
    const {
        fileList,
        setFileList,
        targetLang,
        setTargetLang,
        targetTranslateLang,
        setTargetTranslateLang,
        model,
        setModel,
        isProcessing,
        useBatchMode,
        setUseBatchMode,
        multiSpeaker,
        setMultiSpeaker,
        handleUploadChange,
        handleStartTranscription,
        downloadFile,
        downloadAllFiles,
        clearAllFiles,
        handleReprocess,
        pendingBatches,
        isRecovering,
        recoverBatch,
        isPreviewModalVisible,
        previewContent,
        previewTitle,
        handleOpenPreview,
        handleClosePreview,
    } = useTranscription()

    const { handleEditProvider, handleEditProviderParams, handleTestProvider } = useModelManager()

    // Local UI state
    const [currentPage, setCurrentPage] = useState(1)
    const [youtubeUrl, setYoutubeUrl] = useState("")
    const [isTextModalVisible, setIsTextModalVisible] = useState(false)
    const [textModalContent, setTextModalContent] = useState("")
    const [textModalFileUid, setTextModalFileUid] = useState(null)
    const fileInputRef = useRef(null)

    // Provider derived from model
    const currentProvider = findProviderForModel(model) || "Google"

    // Global config for GlobalDefaults component
    const [globalConfig, setGlobalConfig] = useState({
        language: targetLang || "zh-TW",
        isMultiSpeaker: multiSpeaker,
        speakerCount: 2,
        prompt: "",
        includeTimestamps: true,
    })

    // Sync global config changes to TranscriptionContext
    const handleGlobalConfigChange = (newConfig) => {
        setGlobalConfig(newConfig)
        if (newConfig.language !== targetLang) setTargetLang(newConfig.language)
        if (newConfig.isMultiSpeaker !== multiSpeaker) setMultiSpeaker(newConfig.isMultiSpeaker)
    }

    // Handle files from UploadZone
    const handleFilesAdded = (files) => {
        const newFiles = files.map((file) => ({
            uid: `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            name: file.name,
            size: file.size,
            originFileObj: file,
            status: "waiting",
            percent: 0,
            statusText: "等待處理",
        }))
        const updatedList = [...fileList, ...newFiles]
        setFileList(updatedList)
    }

    // Handle YouTube URL
    const handleAddYoutubeUrl = () => {
        const url = youtubeUrl.trim()
        if (!url) return
        if (!url.includes("youtube.com") && !url.includes("youtu.be")) {
            message.error("請輸入有效的 YouTube 連結")
            return
        }
        const newFile = {
            uid: `yt-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            name: url,
            size: 0,
            status: "waiting",
            percent: 0,
            statusText: "等待處理（YouTube）",
        }
        setFileList([...fileList, newFile])
        setYoutubeUrl("")
        message.success("YouTube 連結已加入佇列")
    }

    // Handle text attachment
    const handleAttachText = (fileUid) => {
        const file = fileList.find((f) => f.uid === fileUid)
        setTextModalFileUid(fileUid)
        setTextModalContent(file?.original_text || "")
        setIsTextModalVisible(true)
    }

    const handleSaveText = () => {
        setFileList((prev) =>
            prev.map((f) =>
                f.uid === textModalFileUid ? { ...f, original_text: textModalContent } : f
            )
        )
        setIsTextModalVisible(false)
        message.success("文本已附加")
    }

    // Handle text from file
    const handleAttachTextFromFile = (fileUid) => {
        setTextModalFileUid(fileUid)
        fileInputRef.current?.click()
    }

    const handleTextFileChange = async (e) => {
        const file = e.target.files?.[0]
        if (!file) return
        try {
            const text = await file.text()
            setFileList((prev) =>
                prev.map((f) =>
                    f.uid === textModalFileUid ? { ...f, original_text: text } : f
                )
            )
            message.success(`已從 "${file.name}" 載入文本`)
        } catch {
            message.error("讀取文本檔案失敗")
        }
        e.target.value = ""
    }

    // Remove file
    const handleRemoveFile = (fileUid) => {
        setFileList((prev) => prev.filter((f) => f.uid !== fileUid))
    }

    // File config update (per-file overrides)
    const handleFileConfigUpdate = (fileId, updates) => {
        setFileList((prev) =>
            prev.map((f) => (f.uid === fileId ? { ...f, ...updates } : f))
        )
    }

    // Apply global config to all files
    const handleApplyAll = () => {
        setFileList((prev) =>
            prev.map((f) => ({
                ...f,
                language: globalConfig.language,
                isMultiSpeaker: globalConfig.isMultiSpeaker,
                speakerCount: globalConfig.speakerCount,
                prompt: globalConfig.prompt,
                includeTimestamps: globalConfig.includeTimestamps,
                hasOverride: false,
            }))
        )
    }

    // Pagination
    const paginatedFiles = fileList.slice(
        (currentPage - 1) * PAGE_SIZE,
        currentPage * PAGE_SIZE
    )

    // File size for CostEstimator
    const totalSizeMB = fileList.reduce((sum, f) => sum + (f.size || 0), 0) / (1024 * 1024)

    // Completed files stats
    const completedFiles = fileList.filter((f) => f.status === "completed")
    const totalTokens = completedFiles.reduce((sum, f) => sum + (f.tokens_used || 0), 0)
    const totalCost = completedFiles.reduce((sum, f) => sum + (f.cost || 0), 0)

    // Download menu items
    const downloadMenuItems = [
        { key: "lrc", label: "LRC 格式" },
        { key: "srt", label: "SRT 格式" },
        { key: "vtt", label: "VTT 格式" },
        { key: "txt", label: "TXT 純文字" },
    ]

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 24 }}>
            {/* 批次恢復提示 */}
            {pendingBatches.length > 0 && (
                <Card
                    size="small"
                    style={{
                        border: "1px solid rgba(212, 167, 45, 0.3)",
                        background: "rgba(212, 167, 45, 0.05)",
                    }}
                >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <HistoryOutlined style={{ color: "#d4a72d" }} />
                            <Text style={{ color: "#e8e8e8" }}>
                                發現 {pendingBatches.length} 個未完成的批次任務
                            </Text>
                        </div>
                        <Space>
                            {pendingBatches.map((batch) => (
                                <Button
                                    key={batch.batch_id}
                                    size="small"
                                    loading={isRecovering}
                                    onClick={() => recoverBatch(batch.batch_id)}
                                >
                                    恢復 ({batch.file_count} 檔)
                                </Button>
                            ))}
                        </Space>
                    </div>
                </Card>
            )}

            {/* 服務商 / 模型 / 批次模式 控制列 */}
            <Card
                size="small"
                style={{ border: "1px solid #3a3a5c" }}
                styles={{ body: { padding: "12px 16px" } }}
            >
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <Text style={{ fontSize: 11, color: "#8888a8" }}>服務商</Text>
                        <Tag color="green">{currentProvider}</Tag>
                    </div>
                    <div style={{ height: 32, width: 1, background: "#3a3a5c" }} />
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <Text style={{ fontSize: 11, color: "#8888a8" }}>模型</Text>
                        <select
                            value={model}
                            onChange={(e) => setModel(e.target.value)}
                            style={{
                                background: "#2a2a48",
                                border: "1px solid #3a3a5c",
                                borderRadius: 6,
                                color: "#e8e8e8",
                                padding: "4px 8px",
                                fontSize: 12,
                            }}
                        >
                            {Object.entries(modelOptions).map(([provider, models]) =>
                                models.map((m) => (
                                    <option key={m.value} value={m.value}>
                                        {m.label}
                                    </option>
                                ))
                            )}
                        </select>
                    </div>
                    <div style={{ height: 32, width: 1, background: "#3a3a5c" }} />
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <Text style={{ fontSize: 11, color: "#8888a8" }}>批次模式 (50% 費用)</Text>
                        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                            <input
                                type="checkbox"
                                checked={useBatchMode}
                                onChange={(e) => setUseBatchMode(e.target.checked)}
                                style={{ accentColor: "#2dd4a8" }}
                            />
                            <Text style={{ fontSize: 12, color: useBatchMode ? "#2dd4a8" : "#8888a8" }}>
                                {useBatchMode ? "已啟用" : "關閉"}
                            </Text>
                        </label>
                    </div>
                    <div style={{ flex: 1 }} />
                    <Space size={6}>
                        <Button size="small" onClick={() => handleEditProvider(currentProvider)}>
                            編輯 API
                        </Button>
                        <Button size="small" onClick={() => handleEditProviderParams(currentProvider)}>
                            編輯參數
                        </Button>
                        <Button size="small" onClick={() => handleTestProvider(currentProvider)}>
                            測試 API
                        </Button>
                    </Space>
                </div>
            </Card>

            {/* Global Defaults */}
            <GlobalDefaults
                config={globalConfig}
                onChange={handleGlobalConfigChange}
                onApplyAll={handleApplyAll}
                fileCount={fileList.length}
            />

            {/* Upload Zone */}
            <UploadZone hasFiles={fileList.length > 0} onFilesAdded={handleFilesAdded} />

            {/* YouTube URL */}
            <div style={{ display: "flex", gap: 8 }}>
                <Input
                    placeholder="YouTube 連結 (例: https://www.youtube.com/watch?v=...)"
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    onPressEnter={handleAddYoutubeUrl}
                    prefix={<Youtube size={14} color="#8888a8" />}
                    style={{ flex: 1 }}
                />
                <Button icon={<LinkOutlined />} onClick={handleAddYoutubeUrl} disabled={!youtubeUrl.trim()}>
                    加入
                </Button>
            </div>

            {/* File List Header */}
            {fileList.length > 0 && (
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <Text style={{ fontSize: 13, color: "#8888a8" }}>
                        {fileList.length} 個檔案
                        {completedFiles.length > 0 && (
                            <span style={{ color: "#2dd4a8", marginLeft: 8 }}>
                                ✓ {completedFiles.length} 完成 · {totalTokens.toLocaleString()} tokens · ${totalCost.toFixed(4)}
                            </span>
                        )}
                    </Text>
                    <Space size={6}>
                        {completedFiles.length > 0 && (
                            <Dropdown
                                menu={{
                                    items: downloadMenuItems,
                                    onClick: ({ key }) => downloadAllFiles(key),
                                }}
                            >
                                <Button size="small" icon={<DownloadOutlined />}>
                                    下載全部
                                </Button>
                            </Dropdown>
                        )}
                        <Popconfirm
                            title="確定清除所有檔案？"
                            onConfirm={clearAllFiles}
                            okText="確定"
                            cancelText="取消"
                        >
                            <Button size="small" danger>
                                清除全部
                            </Button>
                        </Popconfirm>
                    </Space>
                </div>
            )}

            {/* File Cards */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {paginatedFiles.map((file) => (
                    <FileConfigCard
                        key={file.uid}
                        config={{
                            id: file.uid,
                            name: file.name,
                            size: file.size ? `${(file.size / (1024 * 1024)).toFixed(1)} MB` : "YouTube",
                            language: file.language || globalConfig.language,
                            isMultiSpeaker: file.isMultiSpeaker ?? globalConfig.isMultiSpeaker,
                            speakerCount: file.speakerCount ?? globalConfig.speakerCount,
                            prompt: file.prompt ?? globalConfig.prompt,
                            includeTimestamps: file.includeTimestamps ?? globalConfig.includeTimestamps,
                            hasOverride: file.hasOverride || false,
                            // Transcription state
                            status: file.status,
                            statusText: file.statusText,
                            percent: file.percent,
                            tokens_used: file.tokens_used,
                            cost: file.cost,
                            result: file.result,
                            error: file.error,
                            original_text: file.original_text,
                        }}
                        globalConfig={globalConfig}
                        onUpdate={handleFileConfigUpdate}
                        onRemove={handleRemoveFile}
                        onPreview={handleOpenPreview}
                        onDownload={downloadFile}
                        onReprocess={handleReprocess}
                        onAttachText={handleAttachText}
                        onAttachTextFromFile={handleAttachTextFromFile}
                    />
                ))}
            </div>

            {/* Pagination */}
            {fileList.length > PAGE_SIZE && (
                <div style={{ display: "flex", justifyContent: "center" }}>
                    <Pagination
                        current={currentPage}
                        total={fileList.length}
                        pageSize={PAGE_SIZE}
                        onChange={setCurrentPage}
                        size="small"
                        showSizeChanger={false}
                    />
                </div>
            )}

            {/* Cost Estimator & Submit */}
            {fileList.length > 0 && (
                <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: "12px 16px" } }}>
                    <CostEstimator
                        fileCount={fileList.filter((f) => f.status === "waiting" || f.status === "error").length}
                        totalSizeMB={totalSizeMB}
                        isSubmitting={isProcessing}
                        onSubmit={handleStartTranscription}
                    />
                </Card>
            )}

            {/* Preview Modal */}
            <Modal
                title={previewTitle}
                open={isPreviewModalVisible}
                onCancel={handleClosePreview}
                footer={null}
                width={700}
                destroyOnHidden
            >
                <pre style={{
                    maxHeight: 500,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                    fontSize: 13,
                    lineHeight: 1.6,
                    padding: 16,
                    background: "rgba(42, 42, 72, 0.3)",
                    borderRadius: 8,
                }}>
                    {previewContent}
                </pre>
            </Modal>

            {/* Text Attachment Modal */}
            <Modal
                title="附加原始文本"
                open={isTextModalVisible}
                onOk={handleSaveText}
                onCancel={() => setIsTextModalVisible(false)}
                okText="保存"
                cancelText="取消"
                destroyOnHidden
            >
                <TextArea
                    rows={8}
                    value={textModalContent}
                    onChange={(e) => setTextModalContent(e.target.value)}
                    placeholder="貼上原始文本，讓 AI 對照修正轉錄結果..."
                />
            </Modal>

            {/* Hidden file input for text attachment from file */}
            <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.srt,.vtt,.lrc"
                style={{ display: "none" }}
                onChange={handleTextFileChange}
            />
        </div>
    )
}
