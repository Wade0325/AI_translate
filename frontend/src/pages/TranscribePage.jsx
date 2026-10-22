import { useState, useRef } from "react"
import { Card, Typography, Button, Input, Modal, Pagination, Space, Dropdown, Popconfirm, message } from "antd"
import { ReasonText, ReasonTooltip } from "@/components/disabled-reason"
import { UploadZone } from "@/components/transcribe/upload-zone"
import { GlobalDefaults } from "@/components/transcribe/global-defaults"
import { FileConfigCard } from "@/components/transcribe/file-config-card"
import { CostEstimator } from "@/components/transcribe/cost-estimator"
import VadTestModal from "@/components/transcribe/VadTestModal"
import { useTranscription } from "@/context/TranscriptionContext"
import { useModelManager } from "@/components/ModelManager"
import { PROVIDER_LIST_FAILED } from "@/hooks/useProviderList"
import { modelOptions, providerOptions, providerPromptDisabledReason, requiresApiKey } from "@/utils/providerList"
import { filePrompt, followsGlobalPrompt, globalSettingsPatch, promptToSend } from "@/utils/transcribeRequest"
import { api } from "@/services/api"
import { DownloadOutlined } from "@ant-design/icons"
import { downloadFormatsLong } from "@/constants/downloadFormats"
import { randomId } from "@/utils/id"

const { Text } = Typography
const { TextArea } = Input

const PAGE_SIZE = 5

const selectStyle = {
    background: "#2a2a48",
    border: "1px solid #3a3a5c",
    borderRadius: 6,
    color: "#e8e8e8",
    padding: "4px 8px",
    fontSize: 12,
}

export default function TranscribePage() {
    const {
        fileList,
        setFileList,
        targetLang,
        setTargetLang,
        providerList,
        providerListFailed,
        reloadProviderList,
        provider,
        selectProvider,
        model,
        setModel,
        supports,
        promptTemplate,
        disabledReasons,
        isProcessing,
        processingMode,
        setProcessingMode,
        multiSpeaker,
        setMultiSpeaker,
        globalPrompt,
        setGlobalPrompt,
        handleStartTranscription,
        downloadFile,
        downloadAllFiles,
        clearAllFiles,
        handleReprocess,
        cancelTranscription,
        isPreviewModalVisible,
        previewContent,
        previewTitle,
        handleOpenPreview,
        handleClosePreview,
    } = useTranscription()

    const { handleEditProvider, handleEditProviderParams, handleTestProvider } = useModelManager()

    const [currentPage, setCurrentPage] = useState(1)
    const [isTextModalVisible, setIsTextModalVisible] = useState(false)
    const [textModalContent, setTextModalContent] = useState("")
    const [textModalFileUid, setTextModalFileUid] = useState(null)
    const [vadTestingUid, setVadTestingUid] = useState(null)
    const [vadModalOpen, setVadModalOpen] = useState(false)
    const [vadResult, setVadResult] = useState(null)
    const fileInputRef = useRef(null)

    // 「編輯參數」改的是供應商的提示詞範本，和設定頁同一條規則：供應商的模型都不吃提示詞才停用
    const promptTemplateDisabledReason = providerPromptDisabledReason(providerList, provider)

    const [globalConfig, setGlobalConfig] = useState({
        language: targetLang || "zh-TW",
        isMultiSpeaker: multiSpeaker,
        speakerCount: 2,
        prompt: globalPrompt,
        includeTimestamps: true,
    })

    const handleGlobalConfigChange = (newConfig) => {
        setGlobalConfig(newConfig)
        if (newConfig.language !== targetLang) setTargetLang(newConfig.language)
        if (newConfig.isMultiSpeaker !== multiSpeaker) setMultiSpeaker(newConfig.isMultiSpeaker)
        if (newConfig.prompt !== globalPrompt) setGlobalPrompt(newConfig.prompt)
    }

    const handleFilesAdded = (files) => {
        const newFiles = files.map((file) => ({
            uid: randomId("file"),
            name: file.name,
            size: file.size,
            originFileObj: file,
            status: "waiting",
            percent: 0,
            statusText: "等待處理",
        }))
        setFileList((prev) => [...prev, ...newFiles])
    }

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
        message.success("已附加使用者文稿")
    }

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

    const handleRemoveFile = (fileUid) => {
        setFileList((prev) => prev.filter((f) => f.uid !== fileUid))
    }

    const handleFileConfigUpdate = (fileId, updates) => {
        setFileList((prev) =>
            prev.map((f) => (f.uid === fileId ? { ...f, ...updates } : f))
        )
    }

    const handleApplyAll = () => {
        setFileList((prev) => prev.map((f) => ({ ...f, ...globalSettingsPatch(globalConfig) })))
    }

    const handleVadTest = async (fileUid) => {
        const file = fileList.find((f) => f.uid === fileUid)
        if (!file?.originFileObj) {
            message.error("VAD 測試僅支援本機音訊檔案")
            return
        }
        if (isProcessing || vadTestingUid) return

        setVadTestingUid(fileUid)
        setFileList((prev) =>
            prev.map((f) =>
                f.uid === fileUid
                    ? { ...f, status: "processing", statusText: "VAD 測試中...", percent: 0 }
                    : f
            )
        )

        try {
            const formData = new FormData()
            formData.append("file", file.originFileObj)
            const { filename } = await api.upload(formData)
            const result = await api.vad.test({
                filename,
                originalFilename: file.name,
            })
            setVadResult(result)
            setVadModalOpen(true)
            if (result.success) {
                message.success("VAD 測試完成，請查看結果與保存路徑")
            } else {
                message.warning(result.error || "VAD 測試部分失敗")
            }
        } catch (err) {
            message.error(`VAD 測試失敗: ${err.message}`)
        } finally {
            setVadTestingUid(null)
            setFileList((prev) =>
                prev.map((f) =>
                    f.uid === fileUid
                        ? { ...f, status: "waiting", statusText: "等待處理", percent: 0 }
                        : f
                )
            )
        }
    }

    const paginatedFiles = fileList.slice(
        (currentPage - 1) * PAGE_SIZE,
        currentPage * PAGE_SIZE
    )

    const totalSizeMB = fileList.reduce((sum, f) => sum + (f.size || 0), 0) / (1024 * 1024)

    const completedFiles = fileList.filter((f) => f.status === "completed")
    const totalTokens = completedFiles.reduce((sum, f) => sum + (f.tokens_used || 0), 0)
    const totalCost = completedFiles.reduce((sum, f) => sum + (f.cost || 0), 0)

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 24 }}>
            <Card
                size="small"
                style={{ border: "1px solid #3a3a5c" }}
                styles={{ body: { padding: "12px 16px" } }}
            >
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
                    {/* 先選供應商，模型選單只列這個供應商的模型 */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <Text style={{ fontSize: 11, color: "#8888a8" }}>供應商</Text>
                        <select
                            aria-label="供應商"
                            value={provider ?? ""}
                            onChange={(e) => selectProvider(e.target.value)}
                            disabled={!provider}
                            style={selectStyle}
                        >
                            {!provider && (
                                <option value="">{providerListFailed ? "讀取失敗" : "載入中…"}</option>
                            )}
                            {providerOptions(providerList).map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div style={{ height: 32, width: 1, background: "#3a3a5c" }} />
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <Text style={{ fontSize: 11, color: "#8888a8" }}>模型</Text>
                        <select
                            aria-label="模型"
                            value={model ?? ""}
                            onChange={(e) => setModel(e.target.value)}
                            disabled={!provider}
                            style={selectStyle}
                        >
                            {modelOptions(providerList, provider).map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                        {providerListFailed && (
                            <Space size={6}>
                                <ReasonText reason={PROVIDER_LIST_FAILED} />
                                <Button size="small" type="link" onClick={reloadProviderList} style={{ padding: 0, fontSize: 11 }}>
                                    重試
                                </Button>
                            </Space>
                        )}
                    </div>
                    <div style={{ height: 32, width: 1, background: "#3a3a5c" }} />
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <Text style={{ fontSize: 11, color: "#8888a8" }}>處理模式</Text>
                        <select
                            aria-label="處理模式"
                            value={processingMode}
                            onChange={(e) => setProcessingMode(e.target.value)}
                            style={{
                                ...selectStyle,
                                color: processingMode === "standard" ? "#e8e8e8" : "#2dd4a8",
                            }}
                        >
                            <option value="standard">標準（即時）</option>
                            <option value="flex">Flex（50% 費用．分鐘級延遲）</option>
                            <option value="batch" disabled={Boolean(disabledReasons.batch)}>
                                批次（50% 費用．非同步）
                            </option>
                        </select>
                        {processingMode === "batch" && disabledReasons.batch ? (
                            <ReasonText reason={disabledReasons.batch} />
                        ) : (
                            <Text style={{ fontSize: 10, color: "#8888a8" }}>
                                {processingMode === "flex"
                                    ? "失敗時自動降級為標準層級"
                                    : processingMode === "batch"
                                        ? "提交後可離線等待結果"
                                        : "標準同步推論"}
                            </Text>
                        )}
                    </div>
                    <div style={{ flex: 1 }} />
                    <Space size={6}>
                        {/* 和設定頁的金鑰欄位一樣，只有要金鑰的供應商才有（照供應商清單，本機不用） */}
                        {requiresApiKey(providerList, provider) && (
                            <Button size="small" onClick={() => handleEditProvider(provider)}>
                                編輯 API
                            </Button>
                        )}
                        <ReasonTooltip title={promptTemplateDisabledReason}>
                            <Button
                                size="small"
                                disabled={!provider || Boolean(promptTemplateDisabledReason)}
                                onClick={() => handleEditProviderParams(provider)}
                            >
                                編輯參數
                            </Button>
                        </ReasonTooltip>
                        {/* 測模型選單上選的模型，不是設定頁存的預設模型：本機要查的是這個模型的權重 */}
                        <Button size="small" disabled={!provider} onClick={() => handleTestProvider(provider, model)}>
                            測試 API
                        </Button>
                    </Space>
                </div>
            </Card>

            <GlobalDefaults
                config={globalConfig}
                onChange={handleGlobalConfigChange}
                onApplyAll={handleApplyAll}
                fileCount={fileList.length}
                promptDisabledReason={disabledReasons.prompt}
            />

            <UploadZone hasFiles={fileList.length > 0} onFilesAdded={handleFilesAdded} />

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
                                    items: downloadFormatsLong,
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

            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {paginatedFiles.map((file) => (
                    <FileConfigCard
                        key={file.uid}
                        config={{
                            id: file.uid,
                            name: file.name,
                            size: file.size ? `${(file.size / (1024 * 1024)).toFixed(1)} MB` : "",
                            language: file.language || globalConfig.language,
                            isMultiSpeaker: file.isMultiSpeaker ?? globalConfig.isMultiSpeaker,
                            speakerCount: file.speakerCount ?? globalConfig.speakerCount,
                            // 這個檔案自己的提示詞（每檔設定裡編輯的就是它）；清空就回到跟著全域
                            prompt: file.prompt ?? "",
                            followsGlobalPrompt: followsGlobalPrompt(file),
                            // 這個檔案用的提示詞：自己的，沒有就是全域的（還沒輪到提示詞範本）
                            filePrompt: filePrompt(file, globalConfig.prompt),
                            // 檔案卡顯示的提示詞：還沒送出的照送出時的規則算（包括提示詞範本），
                            // 已送出的顯示當初送出的（utils/transcribeRequest.js）
                            promptToSend: promptToSend(file, globalConfig.prompt, promptTemplate, supports),
                            sentPrompt: file.sentPrompt ?? null,
                            includeTimestamps: file.includeTimestamps ?? globalConfig.includeTimestamps,
                            hasOverride: file.hasOverride || false,
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
                        onVadTest={file.originFileObj ? handleVadTest : undefined}
                        onCancel={file.transcribeMode === 'single' ? cancelTranscription : undefined}
                        vadTesting={vadTestingUid === file.uid}
                        disabledReasons={disabledReasons}
                    />
                ))}
            </div>

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

            {fileList.length > 0 && (
                <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: "12px 16px" } }}>
                    <CostEstimator
                        fileCount={fileList.filter((f) => ["waiting", "error", "cancelled"].includes(f.status)).length}
                        totalSizeMB={totalSizeMB}
                        model={model}
                        isSubmitting={isProcessing}
                        onSubmit={handleStartTranscription}
                    />
                </Card>
            )}

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

            <Modal
                title="附加使用者文稿"
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
                    placeholder="貼上完整的文字稿，模型只替它補上時間戳..."
                />
            </Modal>

            <VadTestModal
                open={vadModalOpen}
                result={vadResult}
                onClose={() => setVadModalOpen(false)}
            />

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
