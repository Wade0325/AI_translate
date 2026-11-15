import { useCallback, useEffect, useMemo, useRef } from "react"
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual"
import { isTypingTarget } from "@/utils/segmentCorrections"
import { SegmentRow } from "./segment-row"

/** 使用者自己捲動列表的按鍵（列表取得焦點時瀏覽器拿來捲動的那些）。 */
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "])

/** 第 index 列整列都在列表看得到的範圍裡；沒畫出來（在範圍外）時算看不到。 */
function fullyVisible(container, index) {
    const row = container.querySelector(`[data-index="${index}"]`)
    if (!row) return false
    const box = container.getBoundingClientRect()
    const rect = row.getBoundingClientRect()
    return rect.top >= box.top && rect.bottom <= box.bottom
}

/**
 * 校正頁的片段列表（#347）：只畫看得到的那幾列（2 小時的音檔可能有上千個片段），每列的高度照文字
 * 實際的行數量。正在改的那一列（#348）捲到看不到的地方也照樣畫著，打到一半的字才不會不見。
 *
 * 跟著播放：following 時，followIndex 那一列跑出看得到的範圍就捲到列表中間。使用者自己捲動（滾輪、
 * 觸控、拖捲軸、鍵盤）時呼叫 onUserScroll，由頁面停止跟著播放，不把畫面搶回去；在文字框裡打字用的
 * 空白鍵與方向鍵不算捲動。
 *
 * @param {{
 *   segments: any[],
 *   activeSet: Set<number>,
 *   activeWords: Map<number, number>,
 *   followIndex: number,
 *   following: boolean,
 *   canPlay: boolean,
 *   onUserScroll: () => void,
 *   onSeek: (seconds: number) => void,
 *   editing: import("@/utils/segmentCorrections").Editing | null,
 *   saves: import("@/utils/segmentCorrections").Saves,
 *   singleSpeaker: boolean,
 *   speakerInfo: import("./speaker-menu").SpeakerInfo,
 *   actions: import("./correction-view").RowActions,
 * }} props
 */
export function SegmentList({
    segments, activeSet, activeWords, followIndex, following, canPlay, onUserScroll, onSeek, editing, saves,
    singleSpeaker, speakerInfo, actions,
}) {
    const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null))
    const editingIndex = useMemo(
        () => (editing ? segments.findIndex((s) => s.seg_key === editing.segKey) : -1),
        [segments, editing],
    )
    const rangeExtractor = useCallback((range) => {
        const indexes = defaultRangeExtractor(range)
        if (editingIndex < 0 || indexes.includes(editingIndex)) return indexes
        return [...indexes, editingIndex].sort((a, b) => a - b)
    }, [editingIndex])
    // eslint-disable-next-line react-hooks/incompatible-library -- 列表自己決定哪幾列要重畫，這裡不需要 React Compiler 幫忙記住
    const virtualizer = useVirtualizer({
        count: segments.length,
        getScrollElement: () => containerRef.current,
        estimateSize: () => 43,
        overscan: 8,
        getItemKey: (index) => segments[index].seg_key,
        rangeExtractor,
    })

    useEffect(() => {
        const container = containerRef.current
        if (!container) return undefined
        const stopFollowing = () => onUserScroll()
        // 按在捲軸上：事件的對象是列表本身，不是裡面的某一列
        const onPointerDown = (event) => {
            if (event.target === container) stopFollowing()
        }
        const onKeyDown = (event) => {
            if (SCROLL_KEYS.has(event.key) && !isTypingTarget(event.target)) stopFollowing()
        }
        container.addEventListener("wheel", stopFollowing, { passive: true })
        container.addEventListener("touchmove", stopFollowing, { passive: true })
        container.addEventListener("pointerdown", onPointerDown)
        container.addEventListener("keydown", onKeyDown)
        return () => {
            container.removeEventListener("wheel", stopFollowing)
            container.removeEventListener("touchmove", stopFollowing)
            container.removeEventListener("pointerdown", onPointerDown)
            container.removeEventListener("keydown", onKeyDown)
        }
    }, [onUserScroll])

    useEffect(() => {
        const container = containerRef.current
        if (!following || followIndex < 0 || !container) return
        if (!fullyVisible(container, followIndex)) virtualizer.scrollToIndex(followIndex, { align: "center" })
    }, [following, followIndex, virtualizer])

    return (
        <div
            ref={containerRef}
            tabIndex={0}
            aria-label="片段列表"
            // 撐滿外層（position: relative 的那一格）：高度不靠百分比，外層的高度由 flex 算出來，
            // 列表才有固定的高度、只畫看得到的那幾列
            style={{ position: "absolute", inset: 0, overflowY: "auto", outline: "none" }}
        >
            <div style={{ position: "relative", width: "100%", height: virtualizer.getTotalSize() }}>
                {virtualizer.getVirtualItems().map((item) => (
                    <div
                        key={item.key}
                        data-index={item.index}
                        ref={virtualizer.measureElement}
                        style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${item.start}px)` }}
                    >
                        <SegmentRow
                            segment={segments[item.index]}
                            active={activeSet.has(item.index)}
                            activeWord={activeWords.get(item.index) ?? -1}
                            canPlay={canPlay}
                            onSeek={onSeek}
                            editing={item.index === editingIndex ? editing : null}
                            save={saves[segments[item.index].seg_key]}
                            singleSpeaker={singleSpeaker}
                            speakerInfo={speakerInfo}
                            actions={actions}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}
