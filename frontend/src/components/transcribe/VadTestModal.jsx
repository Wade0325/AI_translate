import { Modal, Typography, Tag, Descriptions, Alert } from "antd"
import { FolderOpen, Scissors } from "lucide-react"

const { Text, Paragraph } = Typography

function SegmentPreview({ segments, truncated }) {
    if (!segments?.length) return null
    return (
        <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: 12, color: "#8888a8" }}>語音片段（前 {segments.length} 段）</Text>
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
                    <Text style={{ fontSize: 11, color: "#8888a8" }}>…更多片段見 segments.json</Text>
                )}
            </div>
        </div>
    )
}

export default function VadTestModal({ open, result, onClose }) {
    if (!result) return null

    const ext = result.speech_extraction
    const split = result.split

    return (
        <Modal
            title={
                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Scissors size={16} color="#2dd4a8" />
                    VAD 切割測試結果
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
                            靜音移除（speech_only）
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
                                    <Descriptions.Item label="片段數">
                                        {ext.segment_count}
                                    </Descriptions.Item>
                                    <Descriptions.Item label="有聲時長">
                                        {ext.speech_duration_seconds}s
                                    </Descriptions.Item>
                                    <Descriptions.Item label="原始時長">
                                        {ext.total_duration_seconds}s
                                    </Descriptions.Item>
                                </Descriptions>
                                <Tag color={ext.would_use_speech_only ? "green" : "default"} style={{ marginTop: 4 }}>
                                    {ext.would_use_speech_only
                                        ? "正式轉錄會使用 speech_only.wav"
                                        : "正式轉錄會跳過 VAD，直接用原檔"}
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
                            靜音分割（part1 / part2）
                        </Text>
                        {split.success ? (
                            <Descriptions
                                column={1}
                                size="small"
                                style={{ marginTop: 8 }}
                                labelStyle={{ color: "#8888a8" }}
                                contentStyle={{ color: "#e8e8e8" }}
                            >
                                <Descriptions.Item label="分割點">
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
                                產物已保存，可本機试听檢查
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
