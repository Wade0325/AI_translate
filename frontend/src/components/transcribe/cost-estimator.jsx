import { FileAudio, Clock, Zap, Sparkles, ArrowRight } from "lucide-react"
import { Typography, Button, Tooltip } from "antd"
import { LoadingOutlined } from "@ant-design/icons"

const { Text } = Typography

export function CostEstimator({
    fileCount,
    totalSizeMB,
    isSubmitting,
    onSubmit,
}) {
    const estimatedMinutes = totalSizeMB * 1
    const estimatedTokens = Math.round(estimatedMinutes * 800)
    const estimatedCost = estimatedTokens * 0.000015
    const estimatedProcessingTime = Math.max(1, Math.round(estimatedMinutes * 0.3))

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
        }}>
            {/* Left: Stats */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                {/* Files & Size pill */}
                <Tooltip title={`${totalSizeMB.toFixed(1)} MB total`}>
                    <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        background: 'rgba(45, 212, 168, 0.08)',
                        border: '1px solid rgba(45, 212, 168, 0.15)',
                        borderRadius: 6, padding: '3px 10px',
                    }}>
                        <FileAudio size={13} color="#2dd4a8" />
                        <Text style={{ fontSize: 12, color: '#c8c8d8' }}>
                            {fileCount} <span style={{ color: '#8888a8' }}>files</span>
                        </Text>
                        <Text style={{ fontSize: 11, color: '#6868888' }}>·</Text>
                        <Text style={{ fontSize: 12, color: '#c8c8d8' }}>{totalSizeMB.toFixed(1)} MB</Text>
                    </span>
                </Tooltip>

                {/* Duration pill */}
                <Tooltip title={`Estimated ${estimatedTokens.toLocaleString()} tokens`}>
                    <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        background: 'rgba(71, 184, 212, 0.08)',
                        border: '1px solid rgba(71, 184, 212, 0.15)',
                        borderRadius: 6, padding: '3px 10px',
                    }}>
                        <Clock size={13} color="#47b8d4" />
                        <Text style={{ fontSize: 12, color: '#c8c8d8' }}>~{estimatedMinutes.toFixed(0)} min</Text>
                    </span>
                </Tooltip>

                {/* Processing pill */}
                <Tooltip title={`Estimated processing time`}>
                    <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        background: 'rgba(139, 92, 246, 0.08)',
                        border: '1px solid rgba(139, 92, 246, 0.15)',
                        borderRadius: 6, padding: '3px 10px',
                    }}>
                        <Zap size={13} color="#8b5cf6" />
                        <Text style={{ fontSize: 12, color: '#c8c8d8' }}>~{estimatedProcessingTime} min</Text>
                    </span>
                </Tooltip>

                {/* Cost highlight */}
                <span style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                    marginLeft: 4,
                }}>
                    <Text style={{ fontSize: 15, fontWeight: 600, color: '#2dd4a8' }}>
                        ${estimatedCost.toFixed(4)}
                    </Text>
                    <Text style={{ fontSize: 11, color: '#6868888' }}>est.</Text>
                </span>
            </div>

            {/* Right: Action */}
            <Button
                type="primary"
                size="middle"
                onClick={onSubmit}
                disabled={fileCount === 0 || isSubmitting}
                icon={isSubmitting ? <LoadingOutlined /> : <Sparkles size={14} />}
                style={{ flexShrink: 0 }}
            >
                {isSubmitting ? "Processing..." : "Start"}
                {!isSubmitting && <ArrowRight size={14} />}
            </Button>
        </div>
    )
}
