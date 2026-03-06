import { useTranscription } from "@/context/TranscriptionContext"
import { ResultBatchGroup } from "@/components/result/result-batch-group"
import { Cpu, Coins, FileAudio, Clock } from "lucide-react"
import { Typography, Tag, Empty } from "antd"

const { Title, Text } = Typography

// ── Summary computation ──────────────────────────────────────

function computeSummary(groups) {
    let totalFiles = 0
    let totalTokens = 0
    let totalCost = 0
    let totalDurationSec = 0 // Note: Original frontend might not provide duration, we'll estimate or default to 0 if not present

    for (const g of groups) {
        for (const f of g.files) {
            totalFiles++
            totalTokens += (f.totalTokens || 0)
            totalCost += (f.cost || 0)
            totalDurationSec += (f.audioDurationSec || 0)
        }
    }

    const h = Math.floor(totalDurationSec / 3600)
    const m = Math.floor((totalDurationSec % 3600) / 60)
    const totalDuration = totalDurationSec > 0 ? (h > 0 ? `${h}h ${m}m` : `${m}m`) : "—"

    return { totalFiles, totalTokens, totalCost, totalDuration }
}

// ── Page ─────────────────────────────────────────────────────

export default function ResultPage() {
    const { fileList, downloadFile } = useTranscription()

    // Filter only completed files
    const completedFiles = fileList.filter(f => f.status === 'completed')

    // Group files for the ResultBatchGroup component
    // If the original context doesn't have batch grouping per say, we'll put them in a "Recent Session" group
    const groups = completedFiles.length > 0 ? [
        {
            group: "Recent Transcriptions",
            files: completedFiles.map(f => ({
                id: f.uid,
                name: f.name,
                language: f.language || "Unknown",
                model: f.model || "Unknown",
                totalTokens: f.tokens_used || 0,
                cost: f.cost || 0,
                audioDurationSec: f.audioDurationSec || 0,
                // We'll pass the full file object to handle downloads or viewing later
                _raw: f
            }))
        }
    ] : []

    const summary = computeSummary(groups)

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
            {completedFiles.length === 0 ? (
                <Empty
                    description={<span style={{ color: '#8888a8' }}>尚無完成的轉錄紀錄。請前往轉錄頁面開始轉錄。</span>}
                    style={{ marginTop: 64 }}
                />
            ) : (
                <>
                    {/* Summary pills */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        <SummaryPill icon={FileAudio} label={`${summary.totalFiles} files`} />
                        <SummaryPill icon={Clock} label={summary.totalDuration} />
                        <SummaryPill icon={Cpu} label={`${summary.totalTokens.toLocaleString()} tokens`} />
                        <SummaryPill icon={Coins} label={`$${summary.totalCost.toFixed(4)}`} highlight />
                    </div>

                    {/* Batch groups */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
                        {groups.map((group) => (
                            <ResultBatchGroup
                                key={group.group}
                                label={group.group}
                                files={group.files}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}

function SummaryPill({
    icon: Icon,
    label,
    highlight,
}) {
    return (
        <Tag
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                borderRadius: 16,
                padding: '4px 12px',
                fontSize: 12,
                border: highlight ? '1px solid rgba(45, 212, 168, 0.3)' : '1px solid #3a3a5c',
                background: highlight ? 'rgba(45, 212, 168, 0.05)' : '#1e1e3a',
                color: highlight ? '#2dd4a8' : '#8888a8',
                fontWeight: highlight ? 500 : 400,
            }}
        >
            <Icon size={12} />
            {label}
        </Tag>
    )
}
