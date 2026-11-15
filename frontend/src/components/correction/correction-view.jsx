import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Button, Progress, Segmented } from "antd"
import { ArrowLeft, Download, LocateFixed, Search } from "lucide-react"
import { api } from "@/services/api"
import { useAudioPlayer } from "@/hooks/useAudioPlayer"
import { useCorrectionShortcuts } from "@/hooks/useCorrectionShortcuts"
import { useReviewStates } from "@/hooks/useReviewStates"
import { useSegmentCorrections } from "@/hooks/useSegmentCorrections"
import { useSegmentSearch } from "@/hooks/useSegmentSearch"
import { useSingleSpeaker } from "@/hooks/useSingleSpeaker"
import { lastStarted, segmentSpans, segmentsAt, wordAt } from "@/utils/playhead"
import {
    FLAGGED, VERIFIED, cursorAfterSeek, filterCounts, keysWithoutReviewState, matchesFilter, nearestVisible,
    reviewProgress, stepVisible, visibleIndexes,
} from "@/utils/reviewStates"
import { REWIND_SECONDS, keepEditorFocus } from "@/utils/segmentCorrections"
import { isFindShortcut } from "@/utils/segmentSearch"
import { speakerCounts } from "@/utils/speakers"
import { TranscriptDownloadMenu } from "@/components/transcript-download-menu"
import { FindBar } from "./find-bar"
import { PlayerBar } from "./player-bar"
import { ReviewToolbar } from "./review-toolbar"
import { SegmentList } from "./segment-list"

/** 保留音檔超過保留天數、被「立即刪除」刪掉，或關掉保留音檔時完成的任務（後端的 audio_available 是 false）。 */
export const AUDIO_GONE = "保留音檔已經不在，無法播放；文字照樣可以校正"
/** 打開頁面之後才讀不到（例如在設定頁立即刪除了），或瀏覽器播不了這個檔。 */
export const AUDIO_FAILED = "保留音檔無法播放；文字照樣可以校正"

/** 說話者的切換（#354）：兩種狀態寫在按鈕上。 */
const SPEAKER_MODES = [
    { value: "single", label: "整份當成同一位" },
    { value: "model", label: "照模型分出的說話者顯示" },
]

/**
 * 片段列表每一列用的動作：改文字、刪掉與還原、改說話者（useSegmentCorrections）、打字時的 Tab 與 Shift+Tab，以及
 * 標確認狀態與換成目前這個片段（#349）。
 *
 * @typedef {ReturnType<typeof useSegmentCorrections>["actions"] & {
 *   playback: (action: import("@/utils/segmentCorrections").PlaybackAction) => void,
 *   select: (segKey: string) => void,
 *   toggleReviewState: (segment: import("@/utils/reviewStates").ReviewedSegment,
 *                       state: import("@/utils/reviewStates").ReviewState) => void,
 * }} RowActions
 */

/** 篩選之後列表是空的時寫的一句。 */
const EMPTY_TEXT = {
    all: "沒有片段",
    flagged: "沒有待查的片段",
    unseen: "沒有還沒看過的片段",
}

/** 篩選的狀態：選的是哪一種，以及選的時候符合的片段鍵（之後不符合了也留在列表裡，見 visibleIndexes）。一開始不篩選。 */
const NO_FILTER = { kind: /** @type {import("@/utils/reviewStates").ReviewFilter} */ ("all"), kept: new Set() }

/** 把焦點從剛按的篩選或播放速度上拿開：焦點留在那裡時方向鍵與空白鍵是給它們的，快捷鍵就不能馬上接著用。 */
function releaseFocus() {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
}

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
 * 確認狀態、快捷鍵、進度與篩選（#349）：上方寫「已確認或校正過的片段數／全部的片段數」；列表可以只看待查的或
 * 還沒看過的；整個流程可以只用鍵盤做完。快捷鍵作用在「目前這個片段」（加一圈框）：↑、↓ 換片段時播放位置跟著跳到
 * 它的開頭；點一列、拖播放進度也會換。播放往下走時不跟著換，聽完一段才按 V 也標得到剛聽完的那一段
 * （見 reviewStates.js）。
 *
 * 說話者（#354）：上方的切換決定整份當成同一位說話者（不顯示說話者，也沒有改說話者的操作），或照模型分出的說話者
 * 顯示；切換是任務的設定，不算校正。顯示說話者時，點片段的說話者可以改這個片段，或把這位說話者全部換成另一位。
 *
 * 尋找與全部取代（#356）：在這一頁按 Ctrl+F 開的是頁面自己的尋找列（FindBar），不是瀏覽器內建的尋找。跳到一個
 * 符合的片段時停止跟著播放捲動；那個片段被篩選掉了時篩選換回全部，才看得到它。尋找不換目前這個片段。
 *
 * @param {{ transcript: {
 *   task_uuid: string,
 *   original_filename?: string | null,
 *   audio_duration_seconds?: number | null,
 *   audio_available: boolean,
 *   single_speaker?: boolean,
 *   next_speaker?: string,
 *   segments: any[],
 * } }} props
 */
export function CorrectionView({ transcript }) {
    const { audioRef, audioProps, playing, time, duration, rate, failed, toggle, seek, skip, setRate } = useAudioPlayer()
    const { segments, saves, editing, lastOperation, nextSpeaker, actions, setReviewStates } = useSegmentCorrections(
        transcript.task_uuid, transcript.segments, transcript.next_speaker,
    )
    const review = useReviewStates(transcript.task_uuid, setReviewStates)
    const { singleSpeaker, switching, switchTo } = useSingleSpeaker(transcript.task_uuid, Boolean(transcript.single_speaker))
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

    // 篩選（#349）與進度
    const [filter, setFilter] = useState(NO_FILTER)
    const visible = useMemo(() => visibleIndexes(segments, filter.kind, filter.kept), [segments, filter])
    const visibleSet = useMemo(() => new Set(visible), [visible])
    const counts = useMemo(() => filterCounts(segments), [segments])
    const progress = useMemo(() => reviewProgress(segments), [segments])
    const withoutReviewState = useMemo(() => keysWithoutReviewState(segments).length, [segments])
    const [confirmOpen, setConfirmOpen] = useState(false)

    // 目前這個片段（快捷鍵作用的片段）：記片段鍵，存檔之後列表換了新的片段物件也不會跑掉
    const [currentKey, setCurrentKey] = useState(/** @type {string | null} */ (segments[0]?.seg_key ?? null))
    const indexOf = useMemo(() => new Map(segments.map((s, i) => [s.seg_key, i])), [segments])
    const current = indexOf.get(currentKey) ?? -1
    // 用快捷鍵換到的片段：列表捲到看得到（每次換都是新的物件）
    const [reveal, setReveal] = useState(/** @type {{ index: number } | null} */ (null))

    const onSeek = useCallback((seconds) => {
        // 點了列表裡的時間或字：從那裡播，並重新跟著播放
        setFollowing(true)
        seek(seconds, { andPlay: true })
    }, [seek])
    const onUserScroll = useCallback(() => setFollowing(false), [])

    // 每位說話者的片段數：內容沒變時保持同一個物件，片段列表的每一列才不會在每次存檔時都重畫
    const speakerCountsJson = useMemo(() => JSON.stringify(speakerCounts(segments)), [segments])
    /** @type {import("./speaker-menu").SpeakerInfo} */
    const speakerInfo = useMemo(() => {
        const counts = /** @type {[string | null, number][]} */ (JSON.parse(speakerCountsJson))
        return {
            speakers: counts.map(([speaker]) => speaker).filter((speaker) => speaker !== null),
            counts: new Map(counts),
            nextSpeaker,
        }
    }, [speakerCountsJson, nextSpeaker])

    /** @type {RowActions} */
    const rowActions = useMemo(() => ({
        ...actions,
        playback: (action) => (action === "rewind" ? skip(-REWIND_SECONDS) : toggle()),
        select: setCurrentKey,
        toggleReviewState: review.actions.toggle,
    }), [actions, skip, toggle, review.actions])

    /** 拖播放進度：目前這個片段換成拖到的那裡正在播放的片段。 */
    const onSliderSeek = (seconds) => {
        seek(seconds)
        const next = cursorAfterSeek(spans, seconds, current, (i) => visibleSet.has(i))
        if (next !== current) setCurrentKey(segments[next].seg_key)
    }

    /** 換到第 index 個片段（在 segments 裡的位置）：列表捲到它，能播放時播放位置跳到它的開頭並重新跟著播放。 */
    const goTo = (index) => {
        if (index < 0 || index === current) return
        setCurrentKey(segments[index].seg_key)
        setReveal({ index })
        if (canPlay) {
            setFollowing(true)
            seek(segments[index].start)
        }
    }

    useCorrectionShortcuts((action) => {
        // 目前這個片段被篩選掉了（例如換到沒有片段的篩選）時，沒有片段可以標或改
        const segment = visibleSet.has(current) ? segments[current] : null
        switch (action) {
            case "toggle-playback":
                if (canPlay) toggle()
                break
            case "rewind":
            case "forward":
                if (canPlay) skip(action === "rewind" ? -REWIND_SECONDS : REWIND_SECONDS)
                break
            case "previous":
            case "next":
                goTo(stepVisible(visible, current, action === "next" ? 1 : -1))
                break
            case "replay":
                if (canPlay && segment) {
                    setFollowing(true)
                    seek(segment.start, { andPlay: true })
                }
                break
            case "edit":
                if (segment) {
                    setReveal({ index: current })
                    actions.startEditing(segment.seg_key)
                }
                break
            case "verify":
            case "flag": {
                if (!segment) break
                const advance = review.actions.toggle(segment, action === "verify" ? VERIFIED : FLAGGED)
                if (advance) goTo(stepVisible(visible, current, 1))
                break
            }
            default:
                break
        }
    }, !confirmOpen)

    /** 換篩選；目前這個片段被篩選掉了時，換到它後面最近的片段。 */
    const applyFilter = (kind) => {
        const kept = new Set(segments.filter((s) => matchesFilter(s, kind)).map((s) => s.seg_key))
        setFilter({ kind, kept })
        const nextVisible = visibleIndexes(segments, kind, kept)
        if (current >= 0 && !nextVisible.includes(current)) {
            const nearest = nearestVisible(nextVisible, current)
            if (nearest >= 0) {
                setCurrentKey(segments[nearest].seg_key)
                setReveal({ index: nearest })
            }
        }
    }

    /** 在工具列選篩選：選完把焦點放掉，方向鍵與空白鍵才是快捷鍵。 */
    const changeFilter = (kind) => {
        applyFilter(kind)
        releaseFocus()
    }

    /** 尋找跳到一個符合的片段（在 segments 裡的位置）：停止跟著播放捲動；它被篩選掉了時換回全部，才看得到它。 */
    const onFindReveal = (index) => {
        setFollowing(false)
        if (!visibleSet.has(index)) applyFilter("all")
    }
    const search = useSegmentSearch(segments, { onReveal: onFindReveal })
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
                <span
                    className="correction-progress"
                    title="已確認或校正過的片段數／全部的片段數"
                    style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#8888a8", fontSize: 12, whiteSpace: "nowrap" }}
                >
                    已確認或校正過
                    <span style={{ color: "#e8e8e8" }}>{progress.done} / {progress.total}</span>
                    <Progress
                        percent={progress.total ? (progress.done / progress.total) * 100 : 0}
                        showInfo={false}
                        size={[72, 6]}
                        strokeColor="#2dd4a8"
                        railColor="#2a2a48"
                    />
                </span>
                <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <span id="speaker-mode-label" style={{ color: "#8888a8", fontSize: 12, whiteSpace: "nowrap" }}>說話者</span>
                    <Segmented
                        size="small"
                        aria-labelledby="speaker-mode-label"
                        options={SPEAKER_MODES}
                        value={singleSpeaker ? "single" : "model"}
                        disabled={switching}
                        onChange={(value) => {
                            // 切換之後收起「復原」：剛才換說話者的提示在整份當成同一位時不該留著
                            actions.dismissUndo()
                            switchTo(value === "single")
                            releaseFocus()
                        }}
                    />
                </div>
                {/* 預設給校正後版本，另有原始轉錄（檔名多一段 .original） */}
                <div style={{ flexShrink: 0, display: "flex", gap: 8 }}>
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
                onSeek={onSliderSeek}
                onRate={(value) => {
                    setRate(value)
                    releaseFocus()
                }}
            />
            <ReviewToolbar
                filter={filter.kind}
                counts={counts}
                onFilter={changeFilter}
                withoutReviewState={withoutReviewState}
                bulkPending={review.bulkPending}
                confirmOpen={confirmOpen}
                onConfirmOpen={setConfirmOpen}
                onMarkRestVerified={() => {
                    review.actions.markRestVerified()
                    releaseFocus()
                }}
            />
            <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
                <SegmentList
                    ref={listRef}
                    segments={segments}
                    visible={visible}
                    currentIndex={current}
                    reveal={reveal}
                    emptyText={EMPTY_TEXT[filter.kind]}
                    activeSet={activeSet}
                    activeWords={activeWords}
                    followIndex={followIndex}
                    following={following && !editing}
                    canPlay={canPlay}
                    onUserScroll={onUserScroll}
                    onSeek={onSeek}
                    editing={editing}
                    saves={saves}
                    singleSpeaker={singleSpeaker}
                    speakerInfo={speakerInfo}
                    actions={rowActions}
                    matches={search.ranges}
                    currentMatch={search.currentKey}
                    revealMatch={search.reveal}
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
                    {review.lastBulk && (
                        <div role="status" style={TOAST_STYLE}>
                            已把 {review.lastBulk.length} 個片段標成已確認
                            <Button type="link" size="small" onMouseDown={keepEditorFocus} onClick={review.actions.undoMarkRestVerified}>
                                復原
                            </Button>
                        </div>
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
