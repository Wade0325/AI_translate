import { memo, useMemo, useState } from "react"
import { Button } from "antd"
import { Check, ChevronDown, ChevronRight, Flag, Trash2 } from "lucide-react"
import { formatClock } from "@/utils/formatters"
import { wordPieces } from "@/utils/playhead"
import { FLAGGED, VERIFIED } from "@/utils/reviewStates"
import { isUserDeleted, keepEditorFocus, shownText } from "@/utils/segmentCorrections"
import { shownSpeaker, showsAsCorrected } from "@/utils/speakers"
import { splitByMatches } from "@/utils/segmentSearch"
import { SegmentEditor } from "./segment-editor"
import { SegmentHistory } from "./segment-history"
import { SpeakerMenu } from "./speaker-menu"

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

/** @type {import("react").CSSProperties} */
const STATUS_STYLE = { fontSize: 12, lineHeight: "26px", whiteSpace: "nowrap", color: "#8888a8" }

/** @type {import("react").CSSProperties} */
const CHIP_STYLE = {
    display: "inline-flex",
    alignItems: "center",
    gap: 2,
    height: 22,
    marginTop: 2,
    padding: "0 6px",
    border: "1px solid #d4a72d80",
    borderRadius: 4,
    background: "rgba(212, 167, 45, 0.12)",
    color: "#d4a72d",
    fontSize: 12,
    cursor: "pointer",
    whiteSpace: "nowrap",
}

/** @type {import("react").CSSProperties} */
const HISTORY_CHIP_STYLE = { ...CHIP_STYLE, borderColor: "#3a3a5c", background: "transparent", color: "#8888a8" }

/**
 * 確認狀態的按鈕（#349）：已確認與待查各一個，標上的那個上色。
 *
 * @type {{ state: import("@/utils/reviewStates").ReviewState, label: string, shortcut: string, color: string,
 *   Icon: typeof Check }[]}
 */
const REVIEW_BUTTONS = [
    { state: VERIFIED, label: "已確認", shortcut: "V", color: "#2dd4a8", Icon: Check },
    { state: FLAGGED, label: "待查", shortcut: "F", color: "#e0884f", Icon: Flag },
]

/**
 * 使用者點了（或拖曳選取了）文字之後，選取的範圍在 container 文字裡的位置，開始改時游標放在那裡。沒有選取時是
 * null（游標放在最後）；拖曳選取了這段文字以外的地方（例如要複製好幾段）時是 false，不開始改。
 *
 * @param {HTMLElement} container
 * @returns {import("@/utils/segmentCorrections").TextSelection | null | false}
 */
function selectionIn(container) {
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) return null
    const range = selection.getRangeAt(0)
    const inside = container.contains(range.startContainer) && container.contains(range.endContainer)
    if (!inside) return range.collapsed ? null : false
    const offset = (node, at) => {
        const before = document.createRange()
        before.selectNodeContents(container)
        before.setEnd(node, at)
        return before.toString().length
    }
    return { start: offset(range.startContainer, range.startOffset), end: offset(range.endContainer, range.endOffset) }
}

/**
 * 一段文字裡符合尋找的字標出來（#356）；沒有符合的字時照原樣。
 *
 * @param {string} text
 * @param {import("@/utils/segmentSearch").TextRange[] | undefined} ranges 整個片段文字裡符合的字
 * @param {string} className 符合的字的 class
 * @param {number} [offset] text 在片段文字裡的開始位置
 */
function marked(text, ranges, className, offset = 0) {
    if (!ranges) return text
    return splitByMatches(text, ranges, offset).map((part, i) => (
        part.match ? <mark key={i} className={className}>{part.text}</mark> : part.text
    ))
}

/**
 * 片段列表的一列：開始時間、說話者與文字（#347），改文字、刪掉與還原（#348），以及改說話者（#354）。
 *
 * - 播放到這段時反白；有逐字時間時標出正在唸的字。點時間從片段的開頭播。
 * - 點文字就開始改，游標放在點的地方；點的是一個字時，同時從那個字開始播（#347），邊聽邊改。
 * - 存檔中、已存與失敗寫在這一列；失敗時寫原因，留著打的字，可以重試或放棄。
 * - 校正過的片段有「校正過」，展開是這個片段的歷程（#355）：每一筆校正紀錄與原始轉錄，可以回到任何一版。
 *   改回和原始轉錄相同、或刪掉的片段照樣有校正紀錄，按「歷程」展開。
 * - 使用者刪掉的片段留在原位，淡化並加上刪除線，可以還原。
 * - 點說話者是選單：改這個片段的說話者，或把這位說話者的片段全部換成另一位。整份當成同一位說話者時不顯示說話者：
 *   只改過說話者的片段不標「校正過」（標「歷程」），歷程裡也不列說話者的校正。
 * - 確認狀態（#349）：已確認與待查各一個按鈕，按一下標上，再按一次清掉；和校正互不影響。用滑鼠按時不拿走焦點：
 *   焦點留在按鈕上時，接著按空白鍵會再按一次這個按鈕，不是播放。
 * - 目前這個片段（快捷鍵作用的片段，#349）加一圈框。點這一列的任何地方，這一列就是目前這個片段。
 * - 尋找時標出符合的字（#356），現在跳到的那個片段標得更明顯。
 *
 * 播放時頁面每一格畫面都重畫，這裡用 memo：只有反白、正在唸的字、存檔狀態或內容變了的那幾列才重畫。
 *
 * @param {{
 *   segment: import("@/utils/segmentCorrections").Segment & { start: number,
 *              words?: { text?: string | null, start: number, end?: number | null }[] | null,
 *              review_state?: string | null },
 *   active: boolean,
 *   current: boolean,
 *   activeWord: number,
 *   canPlay: boolean,
 *   onSeek: (seconds: number) => void,
 *   editing: import("@/utils/segmentCorrections").Editing | null,
 *   save: import("@/utils/segmentCorrections").SaveState | undefined,
 *   singleSpeaker: boolean,
 *   speakerInfo: import("./speaker-menu").SpeakerInfo,
 *   actions: import("./correction-view").RowActions,
 *   matchRanges?: import("@/utils/segmentSearch").TextRange[],
 *   currentMatch?: boolean,
 * }} props
 */
function SegmentRowView({
    segment, active, current, activeWord, canPlay, onSeek, editing, save, singleSpeaker, speakerInfo, actions,
    matchRanges, currentMatch,
}) {
    const [expanded, setExpanded] = useState(false)
    const key = segment.seg_key
    const deleted = isUserDeleted(segment)
    const text = deleted ? segment.deleted_text : shownText(segment, save)
    // 存檔中與失敗時寫的是送出的內容，和逐字時間對不上：整段照原樣寫，不標字
    const pieces = useMemo(
        () => (deleted || text !== segment.text ? null : wordPieces(segment.text, segment.words)),
        [deleted, text, segment],
    )
    // 找的是校正後版本的文字：存檔中與失敗時寫的是送出的內容，對不上，不標
    const matchesShown = !deleted && text === segment.text ? matchRanges : undefined
    const matchClass = currentMatch ? "correction-match correction-match-current" : "correction-match"
    const clock = formatClock(segment.start)
    const saving = save?.status === "saving"
    const corrected = showsAsCorrected(segment, singleSpeaker)
    // 這一列正在改時，按這一列的按鈕不讓文字框失去焦點
    const onButtonMouseDown = editing ? keepEditorFocus : undefined

    const onTextClick = (event) => {
        if (editing || deleted || saving) return
        const selection = selectionIn(event.currentTarget)
        if (selection === false) return
        const word = event.target.closest?.("[data-word]")
        if (word && canPlay) onSeek(segment.words[Number(word.dataset.word)].start)
        actions.startEditing(key, selection)
    }

    let body
    if (editing) {
        body = (
            <SegmentEditor
                initialText={text}
                selection={editing.selection}
                onSave={(draft) => actions.finishEditing(key, draft)}
                onCancel={() => actions.cancelEditing(key)}
                onPlayback={actions.playback}
            />
        )
    } else if (!text) {
        body = <span style={{ color: "#686888" }}>（沒有文字）</span>
    } else if (pieces) {
        let offset = 0
        body = pieces.map((piece, i) => {
            const content = marked(piece.text, matchesShown, matchClass, offset)
            offset += piece.text.length
            return piece.word == null || !canPlay ? (
                <span key={i}>{content}</span>
            ) : (
                <span
                    key={i}
                    data-word={piece.word}
                    className={piece.word === activeWord ? "correction-word correction-word-active" : "correction-word"}
                >
                    {content}
                </span>
            )
        })
    } else {
        body = marked(text, matchesShown, matchClass)
    }

    return (
        <div
            data-active={active || undefined}
            data-current={current || undefined}
            data-deleted={deleted || undefined}
            data-review-state={segment.review_state || undefined}
            onClick={() => actions.select(key)}
            data-current-match={currentMatch || undefined}
            style={{
                ...ROW_STYLE,
                background: active ? "rgba(45, 212, 168, 0.12)" : "transparent",
                borderLeft: `3px solid ${active ? "#2dd4a8" : "transparent"}`,
                boxShadow: current ? "inset 0 0 0 1px #7b7bdb" : undefined,
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
            {!singleSpeaker && (
                <SpeakerMenu
                    segKey={key}
                    speaker={shownSpeaker(segment, save)}
                    info={speakerInfo}
                    disabled={saving || deleted}
                    actions={actions}
                />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
                <div
                    className="correction-text"
                    title={deleted || editing ? undefined : "點一下開始改"}
                    onClick={onTextClick}
                    style={{
                        color: deleted ? "#686888" : "#e8e8e8",
                        fontSize: 14,
                        lineHeight: "26px",
                        overflowWrap: "anywhere",
                        textDecoration: deleted ? "line-through" : undefined,
                        opacity: deleted ? 0.6 : 1,
                        cursor: deleted || editing ? undefined : "text",
                    }}
                >
                    {body}
                </div>
                {save?.status === "failed" && (
                    <div role="alert" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", columnGap: 4, color: "#ff7875", fontSize: 12, lineHeight: "24px" }}>
                        <span>沒有存到：{save.message}</span>
                        <Button size="small" type="link" onMouseDown={onButtonMouseDown} onClick={() => actions.retry(key)}>重試</Button>
                        <Button size="small" type="link" onMouseDown={onButtonMouseDown} onClick={() => actions.discard(key)} style={{ color: "#8888a8" }}>放棄</Button>
                    </div>
                )}
                {expanded && segment.has_correction_records && (
                    <SegmentHistory segment={segment} saving={saving} singleSpeaker={singleSpeaker} actions={actions} onButtonMouseDown={onButtonMouseDown} />
                )}
            </div>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 6, flexShrink: 0 }}>
                {saving && <span style={STATUS_STYLE}>存檔中…</span>}
                {save?.status === "saved" && <span style={{ ...STATUS_STYLE, color: "#2dd4a8" }}>已存</span>}
                {deleted && (
                    <>
                        <span style={STATUS_STYLE}>已刪掉</span>
                        <Button size="small" autoInsertSpace={false} disabled={saving} onClick={() => actions.restore(key)} style={{ marginTop: 2 }}>
                            還原
                        </Button>
                    </>
                )}
                {segment.has_correction_records && (
                    <button
                        type="button"
                        aria-expanded={expanded}
                        title={expanded ? "收起歷程" : "看這個片段的每一次校正，可以回到任何一版"}
                        onMouseDown={onButtonMouseDown}
                        onClick={() => setExpanded((open) => !open)}
                        style={corrected && !deleted ? CHIP_STYLE : HISTORY_CHIP_STYLE}
                    >
                        {corrected && !deleted ? "校正過" : "歷程"}
                        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </button>
                )}
                {!deleted && (
                    <Button
                        type="text"
                        size="small"
                        aria-label="刪掉這個片段"
                        title="刪掉這個片段"
                        icon={<Trash2 size={14} />}
                        disabled={saving || !text}
                        onMouseDown={onButtonMouseDown}
                        onClick={() => actions.remove(key)}
                        style={{ marginTop: 1, color: "#8888a8" }}
                    />
                )}
                {REVIEW_BUTTONS.map(({ state, label, shortcut, color, Icon }) => {
                    const pressed = segment.review_state === state
                    return (
                        <Button
                            key={state}
                            type="text"
                            size="small"
                            aria-label={label}
                            aria-pressed={pressed}
                            title={`${pressed ? "取消" : "標成"}${label}（${shortcut}）`}
                            icon={<Icon size={14} />}
                            onMouseDown={keepEditorFocus}
                            onClick={() => actions.toggleReviewState(segment, state)}
                            style={{ marginTop: 1, color: pressed ? color : "#55557a", background: pressed ? `${color}26` : undefined }}
                        />
                    )
                })}
            </div>
        </div>
    )
}

export const SegmentRow = memo(SegmentRowView)
