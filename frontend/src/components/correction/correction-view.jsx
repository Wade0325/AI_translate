import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "antd"
import { ArrowLeft, Download, LocateFixed, Search } from "lucide-react"
import { api } from "@/services/api"
import { useAudioPlayer } from "@/hooks/useAudioPlayer"
import { useSegmentCorrections } from "@/hooks/useSegmentCorrections"
import { useSegmentSearch } from "@/hooks/useSegmentSearch"
import { lastStarted, segmentSpans, segmentsAt, wordAt } from "@/utils/playhead"
import { REWIND_SECONDS, keepEditorFocus } from "@/utils/segmentCorrections"
import { isFindShortcut } from "@/utils/segmentSearch"
import { TranscriptDownloadMenu } from "@/components/transcript-download-menu"
import { FindBar } from "./find-bar"
import { PlayerBar } from "./player-bar"
import { SegmentList } from "./segment-list"

/** 保留音檔超過保留天數、被「立即刪除」刪掉，或關掉保留音檔時完成的任務（後端的 audio_available 是 false）。 */
export const AUDIO_GONE = "保留音檔已經不在，無法播放；文字照樣可以校正"
/** 打開頁面之後才讀不到（例如在設定頁立即刪除了），或瀏覽器播不了這個檔。 */
export const AUDIO_FAILED = "保留音檔無法播放；文字照樣可以校正"

/**
 * 片段列表每一列用的動作：改文字、刪掉與還原（useSegmentCorrections），以及打字時的 Tab 與 Shift+Tab。
 *
 * @typedef {ReturnType<typeof useSegmentCorrections>["actions"]
 *   & { playback: (action: import("@/utils/segmentCorrections").PlaybackAction) => void }} RowActions
 */

/**
 * 按 Ctrl+F 時選起來的字（一行、不太長時）拿來當要找的字，和瀏覽器的尋找一樣：片段的文字，或正在改的文字框裡
 * 選起來的字。焦點在尋找列的輸入框裡時不算。
 */
function selectedSearchText() {
    const active = document.activeElement
    let text = ""
    if (active instanceof HTMLTextAreaElement) text = active.value.slice(active.selectionStart, active.selectionEnd)
    else if (!(active instanceof HTMLInputElement)) text = window.getSelection()?.toString() ?? ""
    return text && !/[\r\n]/.test(text) && text.length <= 100 ? text : ""
}

/** @type {import("react").CSSProperties} */
const TOAST_STYLE = {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "4px 6px 4px 14px",
    borderRadius: 6,
    background: "#2a2a48",
    border: "1px solid #3a3a5c",
    color: "#e8e8e8",
    fontSize: 13,
    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.4)",
}

/**
 * 校正頁的內容：上方固定的播放列，下方是片段列表（#347）。播放時反白正在唸的片段並跟著捲動；使用者自己捲走時
 * 停止跟著，給一個「回到正在播放的片段」的按鈕。
 *
 * 改文字、刪掉與還原片段（#348）：點文字就改，每一次校正馬上存，沒有整頁的存檔鈕；存完出現幾秒的「已存檔，
 * 復原」。正在改的時候不跟著播放捲動，免得改到一半那一列被捲走；改完再接著跟。
 *
 * 尋找與全部取代（#356）：在這一頁按 Ctrl+F 開的是頁面自己的尋找列（FindBar），不是瀏覽器內建的尋找。跳到一個
 * 符合的片段時停止跟著播放捲動。
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
    const { audioRef, audioProps, playing, time, duration, rate, failed, toggle, seek, skip, setRate } = useAudioPlayer()
    const { segments, saves, editing, lastOperation, actions } = useSegmentCorrections(transcript.task_uuid, transcript.segments)
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

    const search = useSegmentSearch(segments, { onReveal: onUserScroll })
    const { openFind, close: closeFind } = search.actions
    const listRef = useRef(/** @type {HTMLDivElement | null} */ (null))
    const onCloseFind = useCallback(() => {
        closeFind()
        listRef.current?.focus({ preventScroll: true })
    }, [closeFind])

    // 在校正頁按 Ctrl+F 開頁面自己的尋找：片段列表只畫看得到的那幾列，瀏覽器內建的尋找找不到其他片段
    useEffect(() => {
        const onKeyDown = (event) => {
            if (!isFindShortcut(event)) return
            event.preventDefault()
            openFind(selectedSearchText())
        }
        window.addEventListener("keydown", onKeyDown)
        return () => window.removeEventListener("keydown", onKeyDown)
    }, [openFind])

    /** @type {RowActions} */
    const rowActions = useMemo(() => ({
        ...actions,
        playback: (action) => (action === "rewind" ? skip(-REWIND_SECONDS) : toggle()),
    }), [actions, skip, toggle])

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
                {/* 預設給校正後版本，另有原始轉錄（檔名多一段 .original） */}
                <div style={{ marginLeft: "auto", flexShrink: 0, display: "flex", gap: 8 }}>
                    <Button
                        size="small"
                        icon={<Search size={14} />}
                        title="尋找與取代（Ctrl+F）"
                        autoInsertSpace={false}
                        onClick={() => openFind()}
                    >
                        尋找
                    </Button>
                    <TranscriptDownloadMenu
                        taskUuid={transcript.task_uuid}
                        fileName={transcript.original_filename}
                        withOriginal
                        trigger={["click"]}
                    >
                        <Button size="small" icon={<Download size={14} />}>下載</Button>
                    </TranscriptDownloadMenu>
                </div>
            </div>
            {search.open && <FindBar search={search} onReplaceAll={actions.replaceAll} onClose={onCloseFind} />}
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
                    ref={listRef}
                    segments={segments}
                    activeSet={activeSet}
                    activeWords={activeWords}
                    followIndex={followIndex}
                    following={following && !editing}
                    canPlay={canPlay}
                    onUserScroll={onUserScroll}
                    onSeek={onSeek}
                    editing={editing}
                    saves={saves}
                    actions={rowActions}
                    matches={search.ranges}
                    currentMatch={search.currentKey}
                    reveal={search.reveal}
                />
                <div style={{ position: "absolute", left: "50%", bottom: 16, transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
                    {!following && followIndex >= 0 && (
                        <Button
                            type="primary"
                            icon={<LocateFixed size={14} />}
                            onClick={() => setFollowing(true)}
                            style={{ boxShadow: "0 4px 12px rgba(0, 0, 0, 0.4)" }}
                        >
                            回到正在播放的片段
                        </Button>
                    )}
                    {lastOperation && (
                        <div role="status" style={TOAST_STYLE}>
                            {lastOperation.label}
                            <Button type="link" size="small" onMouseDown={keepEditorFocus} onClick={actions.undo}>
                                復原
                            </Button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
