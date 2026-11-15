import { memo, useMemo } from "react"
import { formatClock } from "@/utils/formatters"
import { wordPieces } from "@/utils/playhead"

/** 說話者編號（S0、S1…）的顏色：照編號輪流用，同一位說話者在整份裡顏色不變。 */
const SPEAKER_COLORS = ["#2dd4a8", "#d4a72d", "#47b8d4", "#e07a9f", "#8b5cf6", "#e0884f", "#7fc97f", "#c9c95c"]

function speakerColor(speaker) {
    const n = Number(/\d+/.exec(speaker)?.[0] ?? 0)
    return SPEAKER_COLORS[n % SPEAKER_COLORS.length]
}

const ROW_STYLE = {
    display: "flex",
    alignItems: "flex-start",
    gap: 12,
    padding: "8px 16px 8px 13px",
    borderBottom: "1px solid #2a2a48",
}

/** @type {import("react").CSSProperties} */
const TIME_STYLE = {
    flexShrink: 0,
    width: 64,
    padding: 0,
    border: 0,
    background: "none",
    color: "#2dd4a8",
    fontSize: 12,
    lineHeight: "26px",
    textAlign: "left",
}

/**
 * 片段列表的一列：開始時間、說話者與文字（#347）。播放到這段時反白；有逐字時間時標出正在唸的字，
 * 點一個字從那個字開始播，點時間從片段的開頭播。
 *
 * 播放時頁面每一格畫面都重畫，這裡用 memo：只有反白或正在唸的字變了的那幾列才重畫。
 *
 * @param {{
 *   segment: { start: number, speaker?: string | null, text?: string | null,
 *              words?: { text?: string | null, start: number, end?: number | null }[] | null },
 *   active: boolean,
 *   activeWord: number,
 *   canPlay: boolean,
 *   onSeek: (seconds: number) => void,
 * }} props
 */
function SegmentRowView({ segment, active, activeWord, canPlay, onSeek }) {
    const pieces = useMemo(() => wordPieces(segment.text, segment.words), [segment])
    const clock = formatClock(segment.start)

    return (
        <div
            data-active={active || undefined}
            style={{
                ...ROW_STYLE,
                background: active ? "rgba(45, 212, 168, 0.12)" : "transparent",
                borderLeft: `3px solid ${active ? "#2dd4a8" : "transparent"}`,
            }}
        >
            {canPlay ? (
                <button
                    type="button"
                    className="correction-clock"
                    title="從這個片段的開頭播放"
                    onClick={() => onSeek(segment.start)}
                    style={{ ...TIME_STYLE, cursor: "pointer" }}
                >
                    {clock}
                </button>
            ) : (
                <span className="correction-clock" style={{ ...TIME_STYLE, color: "#8888a8" }}>{clock}</span>
            )}
            <span
                style={{
                    flexShrink: 0,
                    minWidth: 28,
                    color: segment.speaker ? speakerColor(segment.speaker) : "#686888",
                    fontSize: 12,
                    fontWeight: 600,
                    lineHeight: "26px",
                }}
            >
                {segment.speaker || ""}
            </span>
            <div style={{ flex: 1, minWidth: 0, color: "#e8e8e8", fontSize: 14, lineHeight: "26px", overflowWrap: "anywhere" }}>
                {!segment.text ? (
                    <span style={{ color: "#686888" }}>（沒有文字）</span>
                ) : pieces ? (
                    pieces.map((piece, i) => (piece.word == null || !canPlay ? (
                        <span key={i}>{piece.text}</span>
                    ) : (
                        <span
                            key={i}
                            className={piece.word === activeWord ? "correction-word correction-word-active" : "correction-word"}
                            onClick={() => onSeek(segment.words[piece.word].start)}
                        >
                            {piece.text}
                        </span>
                    )))
                ) : (
                    segment.text
                )}
            </div>
        </div>
    )
}

export const SegmentRow = memo(SegmentRowView)
