import { memo, useMemo, useState } from "react"
import { Button } from "antd"
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react"
import { formatClock } from "@/utils/formatters"
import { wordPieces } from "@/utils/playhead"
import { isUserDeleted, keepEditorFocus, shownText, speakerCorrected } from "@/utils/segmentCorrections"
import { NO_SPEAKER_LABEL, shownSpeaker, showsAsCorrected } from "@/utils/speakers"
import { SegmentEditor } from "./segment-editor"
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
 * 片段列表的一列：開始時間、說話者與文字（#347），改文字、刪掉與還原（#348），以及改說話者（#354）。
 *
 * - 播放到這段時反白；有逐字時間時標出正在唸的字。點時間從片段的開頭播。
 * - 點文字就開始改，游標放在點的地方；點的是一個字時，同時從那個字開始播（#347），邊聽邊改。
 * - 存檔中、已存與失敗寫在這一列；失敗時寫原因，留著打的字，可以重試或放棄。
 * - 校正過的片段有「校正過」，展開看得到原始轉錄，可以一鍵回到原始轉錄。
 * - 使用者刪掉的片段留在原位，淡化並加上刪除線，可以還原。
 * - 點說話者是選單：改這個片段的說話者，或把這位說話者的片段全部換成另一位。整份當成同一位說話者時不顯示說話者，
 *   只改過說話者的片段也不標「校正過」。
 *
 * 播放時頁面每一格畫面都重畫，這裡用 memo：只有反白、正在唸的字、存檔狀態或內容變了的那幾列才重畫。
 *
 * @param {{
 *   segment: import("@/utils/segmentCorrections").Segment & { start: number,
 *              words?: { text?: string | null, start: number, end?: number | null }[] | null },
 *   active: boolean,
 *   activeWord: number,
 *   canPlay: boolean,
 *   onSeek: (seconds: number) => void,
 *   editing: import("@/utils/segmentCorrections").Editing | null,
 *   save: import("@/utils/segmentCorrections").SaveState | undefined,
 *   singleSpeaker: boolean,
 *   speakerInfo: import("./speaker-menu").SpeakerInfo,
 *   actions: import("./correction-view").RowActions,
 * }} props
 */
function SegmentRowView({ segment, active, activeWord, canPlay, onSeek, editing, save, singleSpeaker, speakerInfo, actions }) {
    const [expanded, setExpanded] = useState(false)
    const key = segment.seg_key
    const deleted = isUserDeleted(segment)
    const text = deleted ? segment.deleted_text : shownText(segment, save)
    // 存檔中與失敗時寫的是送出的內容，和逐字時間對不上：整段照原樣寫，不標字
    const pieces = useMemo(
        () => (deleted || text !== segment.text ? null : wordPieces(segment.text, segment.words)),
        [deleted, text, segment],
    )
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
        body = pieces.map((piece, i) => (piece.word == null || !canPlay ? (
            <span key={i}>{piece.text}</span>
        ) : (
            <span
                key={i}
                data-word={piece.word}
                className={piece.word === activeWord ? "correction-word correction-word-active" : "correction-word"}
            >
                {piece.text}
            </span>
        )))
    } else {
        body = text
    }

    return (
        <div
            data-active={active || undefined}
            data-deleted={deleted || undefined}
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
                {expanded && corrected && !deleted && (
                    <div style={{ marginTop: 6, padding: "6px 10px", borderRadius: 4, background: "#1a1a34", border: "1px solid #2a2a48" }}>
                        <div style={{ color: "#8888a8", fontSize: 12, lineHeight: "20px" }}>原始轉錄</div>
                        <div style={{ color: "#b8b8d0", fontSize: 13, lineHeight: "22px", overflowWrap: "anywhere" }}>
                            {!singleSpeaker && speakerCorrected(segment) && (
                                <span style={{ marginRight: 8, fontWeight: 600 }}>{segment.original_speaker || `（${NO_SPEAKER_LABEL}）`}</span>
                            )}
                            {segment.original_text || "（沒有文字）"}
                        </div>
                        <Button
                            size="small"
                            style={{ marginTop: 6 }}
                            disabled={saving}
                            onMouseDown={onButtonMouseDown}
                            onClick={() => {
                                setExpanded(false)
                                actions.revert(key)
                            }}
                        >
                            回到原始轉錄
                        </Button>
                    </div>
                )}
            </div>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 6, flexShrink: 0 }}>
                {saving && <span style={STATUS_STYLE}>存檔中…</span>}
                {save?.status === "saved" && <span style={{ ...STATUS_STYLE, color: "#2dd4a8" }}>已存</span>}
                {deleted ? (
                    <>
                        <span style={STATUS_STYLE}>已刪掉</span>
                        <Button size="small" autoInsertSpace={false} disabled={saving} onClick={() => actions.restore(key)} style={{ marginTop: 2 }}>
                            還原
                        </Button>
                    </>
                ) : (
                    <>
                        {corrected && (
                            <button
                                type="button"
                                aria-expanded={expanded}
                                title={expanded ? "收起原始轉錄" : "看原始轉錄"}
                                onMouseDown={onButtonMouseDown}
                                onClick={() => setExpanded((open) => !open)}
                                style={CHIP_STYLE}
                            >
                                校正過
                                {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                            </button>
                        )}
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
                    </>
                )}
            </div>
        </div>
    )
}

export const SegmentRow = memo(SegmentRowView)
