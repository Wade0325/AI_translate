import { Modal, Typography, Tag, Descriptions, Alert } from "antd"
import { FolderOpen, Scissors } from "lucide-react"

const { Text, Paragraph } = Typography

function SegmentPreview({ segments, truncated }) {
    if (!segments?.length) return null
    return (
        <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12, color: "#8888a8" }}>有聲段（前 {segments.length} 段）</Text>
            <div
                style={{
                    marginTop: 6,
                    maxHeight: 160,
                    overflow: "auto",
                    background: "#141428",
                    borderRadius: 6,
                    padding: "8px 10px",
                    fontFamily: "monospace",
                    fontSize: 11,
                    color: "#bbb",
                }}
            >
                {segments.map((seg, i) => (
                    <div key={i}>
                        #{i + 1} {seg.start.toFixed(2)}s → {seg.end.toFixed(2)}s
                        {" "}({(seg.end - seg.start).toFixed(2)}s)
                    </div>
                ))}
                {truncated && (
                    <Text style={{ fontSize: 11, color: "#8888a8" }}>…更多有聲段見 segments.json</Text>
                )}
            </div>
        </div>
    )
}

/**
 * 正式轉錄會怎麼處理這個音檔。would_use_speech_only 是語音佔比低於門檻，也就是去靜音的模型會用
 * speech_only.wav；不去靜音的模型（#95）一律用原檔，低於門檻時切在靜音的正中間，否則和去靜音的
 * 模型一樣由 Silero 找切點。
 */
function transcriptionNote(ext, removesSilence) {
    if (removesSilence) {
        return ext.would_use_speech_only
            ? { color: "green", text: "正式轉錄會使用 speech_only.wav" }
            : { color: "default", text: "正式轉錄不去靜音，直接用原檔" }
    }
    return {
        color: "default",
        text: ext.would_use_speech_only
            ? "所選的模型不去靜音：正式轉錄用原檔，分段轉錄時切在靜音的正中間"
            : "所選的模型不去靜音：正式轉錄用原檔，分段轉錄時由 Silero 找切點",
    }
}

/** removesSilence：所選的模型轉錄前會不會去靜音（模型能力），決定對話框怎麼說明正式轉錄。 */
export default function VadTestModal({ open, result, removesSilence = true, onClose }) {
    if (!result) return null

    const ext = result.speech_extraction
    const split = result.split
    const note = ext?.success ? transcriptionNote(ext, removesSilence) : null

    return (
        <Modal
            title={
                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Scissors size={16} color="#2dd4a8" />
                    去靜音與切點預覽
                </span>
            }
            open={open}
            onCancel={onClose}
            footer={null}
            width={560}
        >
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div>
                    <Text strong style={{ color: "#e8e8e8" }}>{result.original_filename}</Text>
                    {!result.success && (
                        <Alert
                            type="warning"
                            showIcon
                            message={result.error || "部分步驟失敗"}
                            style={{ marginTop: 8 }}
                        />
                    )}
                </div>

                {ext && (
                    <div style={{ border: "1px solid #3a3a5c", borderRadius: 8, padding: 12 }}>
                        <Text style={{ fontSize: 13, fontWeight: 600, color: "#e8e8e8" }}>
                            去靜音（speech_only）
                        </Text>
                        {ext.success ? (
                            <>
                                <Descriptions
                                    column={2}
                                    size="small"
                                    style={{ marginTop: 8 }}
                                    labelStyle={{ color: "#8888a8" }}
                                    contentStyle={{ color: "#e8e8e8" }}
                                >
                                    <Descriptions.Item label="語音佔比">
                                        {(ext.speech_ratio * 100).toFixed(1)}%
                                    </Descriptions.Item>
                                    <Descriptions.Item label="有聲段數">
                                        {ext.segment_count}
                                    </Descriptions.Item>
                                    <Descriptions.Item label="有聲時長">
                                        {ext.speech_duration_seconds}s
                                    </Descriptions.Item>
                                    <Descriptions.Item label="原始時長">
                                        {ext.total_duration_seconds}s
                                    </Descriptions.Item>
                                </Descriptions>
                                <Tag color={note.color} style={{ marginTop: 4 }}>
                                    {note.text}
                                </Tag>
                                <SegmentPreview
                                    segments={ext.segments}
                                    truncated={ext.segments_truncated}
                                />
                            </>
                        ) : (
                            <Alert type="error" message={ext.error} style={{ marginTop: 8 }} />
                        )}
                    </div>
                )}

                {split && (
                    <div style={{ border: "1px solid #3a3a5c", borderRadius: 8, padding: 12 }}>
                        <Text style={{ fontSize: 13, fontWeight: 600, color: "#e8e8e8" }}>
                            切點（part1 / part2）
                        </Text>
                        {split.success ? (
                            <Descriptions
                                column={1}
                                size="small"
                                style={{ marginTop: 8 }}
                                labelStyle={{ color: "#8888a8" }}
                                contentStyle={{ color: "#e8e8e8" }}
                            >
                                <Descriptions.Item label="切點">
                                    {split.split_point_seconds}s
                                </Descriptions.Item>
                                <Descriptions.Item label="Part 1">
                                    {split.part1_duration_seconds}s
                                </Descriptions.Item>
                                <Descriptions.Item label="Part 2">
                                    {split.part2_duration_seconds}s
                                </Descriptions.Item>
                            </Descriptions>
                        ) : (
                            <Alert type="warning" message={split.error} style={{ marginTop: 8 }} />
                        )}
                    </div>
                )}

                {result.artifact_dir && (
                    <div
                        style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: 8,
                            padding: 10,
                            background: "rgba(45, 212, 168, 0.08)",
                            border: "1px solid rgba(45, 212, 168, 0.25)",
                            borderRadius: 8,
                        }}
                    >
                        <FolderOpen size={16} color="#2dd4a8" style={{ marginTop: 2, flexShrink: 0 }} />
                        <div>
                            <Text style={{ fontSize: 12, color: "#2dd4a8", fontWeight: 600 }}>
                                產物已保存，可在本機試聽檢查
                            </Text>
                            <Paragraph
                                copyable
                                style={{ margin: "4px 0 0", fontSize: 11, color: "#8888a8", wordBreak: "break-all" }}
                            >
                                {result.artifact_dir}
                            </Paragraph>
                            <Text style={{ fontSize: 11, color: "#8888a8" }}>
                                含 speech_only.wav、part1/part2.wav、segments.json、manifest.json
                            </Text>
                        </div>
                    </div>
                )}
            </div>
        </Modal>
    )
}
