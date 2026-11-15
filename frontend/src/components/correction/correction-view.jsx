import { useCallback, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "antd"
import { ArrowLeft, LocateFixed } from "lucide-react"
import { api } from "@/services/api"
import { useAudioPlayer } from "@/hooks/useAudioPlayer"
import { lastStarted, segmentSpans, segmentsAt, wordAt } from "@/utils/playhead"
import { PlayerBar } from "./player-bar"
import { SegmentList } from "./segment-list"

/** 保留音檔超過保留天數、被「立即刪除」刪掉，或關掉保留音檔時完成的任務（後端的 audio_available 是 false）。 */
export const AUDIO_GONE = "保留音檔已經不在，無法播放；文字照樣看得到"
/** 打開頁面之後才讀不到（例如在設定頁立即刪除了），或瀏覽器播不了這個檔。 */
export const AUDIO_FAILED = "保留音檔無法播放；文字照樣看得到"

/**
 * 校正頁的內容（#347，這一刀唯讀）：上方固定的播放列，下方是片段列表。播放時反白正在唸的片段並
 * 跟著捲動；使用者自己捲走時停止跟著，給一個「回到正在播放的片段」的按鈕。
 *
 * @param {{ transcript: {
 *   task_uuid: string,
 *   original_filename?: string | null,
 *   audio_duration_seconds?: number | null,
 *   audio_available: boolean,
 *   segments: any[],
 * } }} props
 */
export function CorrectionView({ transcript }) {
    const { audioRef, audioProps, playing, time, duration, rate, failed, toggle, seek, setRate } = useAudioPlayer()
    const { segments } = transcript
    const total = duration ?? transcript.audio_duration_seconds ?? 0
    const canPlay = transcript.audio_available && !failed

    const spans = useMemo(() => segmentSpans(segments, total), [segments, total])
    // 不能播放時沒有正在唸的片段：不反白、不跟著捲動，也不出現「回到正在播放的片段」
    const active = useMemo(() => (canPlay ? segmentsAt(spans, time) : []), [canPlay, spans, time])
    const activeSet = useMemo(() => new Set(active), [active])
    const activeWords = useMemo(
        () => new Map(active.map((i) => [i, wordAt(segments[i].words, time, spans[i].end)])),
        [active, segments, spans, time],
    )
    const followIndex = canPlay ? lastStarted(spans, time) : -1
    const [following, setFollowing] = useState(true)

    const onSeek = useCallback((seconds) => {
        // 點了列表裡的時間或字：從那裡播，並重新跟著播放
        setFollowing(true)
        seek(seconds, { andPlay: true })
    }, [seek])
    const onUserScroll = useCallback(() => setFollowing(false), [])

    let notice = null
    if (!transcript.audio_available) notice = AUDIO_GONE
    else if (failed) notice = AUDIO_FAILED

    return (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {transcript.audio_available && (
                <audio
                    ref={audioRef}
                    src={api.transcripts.audioUrl(transcript.task_uuid)}
                    preload="metadata"
                    {...audioProps}
                />
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", flexShrink: 0 }}>
                <Link to="/history" style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#8888a8", fontSize: 13 }}>
                    <ArrowLeft size={14} /> History
                </Link>
                <span style={{ color: "#e8e8e8", fontSize: 15, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {transcript.original_filename || "—"}
                </span>
                <span style={{ color: "#8888a8", fontSize: 12, whiteSpace: "nowrap" }}>{segments.length} 個片段</span>
            </div>
            <PlayerBar
                playing={playing}
                time={time}
                total={total}
                rate={rate}
                notice={notice}
                onToggle={toggle}
                onSeek={seek}
                onRate={setRate}
            />
            <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
                <SegmentList
                    segments={segments}
                    activeSet={activeSet}
                    activeWords={activeWords}
                    followIndex={followIndex}
                    following={following}
                    canPlay={canPlay}
                    onUserScroll={onUserScroll}
                    onSeek={onSeek}
                />
                {!following && followIndex >= 0 && (
                    <Button
                        type="primary"
                        icon={<LocateFixed size={14} />}
                        onClick={() => setFollowing(true)}
                        style={{ position: "absolute", left: "50%", bottom: 16, transform: "translateX(-50%)", boxShadow: "0 4px 12px rgba(0, 0, 0, 0.4)" }}
                    >
                        回到正在播放的片段
                    </Button>
                )}
            </div>
        </div>
    )
}
