import { useCallback, useEffect, useMemo, useRef } from "react"
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual"
import { isTypingTarget } from "@/utils/segmentCorrections"
import { SegmentRow } from "./segment-row"

/**
 * 使用者自己捲動列表的按鍵（列表取得焦點時瀏覽器拿來捲動的那些）。↑、↓ 與空白鍵是校正頁的快捷鍵（#349），
 * 換片段與播放，不捲動列表，不在這裡。
 */
const SCROLL_KEYS = new Set(["PageUp", "PageDown", "Home", "End"])

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
 * 篩選（#349）：只列 visible 裡的片段（片段在 segments 裡的位置）。其他以位置表示的參數（activeSet、
 * followIndex、currentIndex、reveal）也都是在 segments 裡的位置；篩選掉的片段不畫，也不捲過去。每一列的
 * data-index 是它在列表裡的第幾列。
 *
 * 跟著播放：following 時，followIndex 那一列跑出看得到的範圍就捲到列表中間。使用者自己捲動（滾輪、
 * 觸控、拖捲軸、鍵盤）時呼叫 onUserScroll，由頁面停止跟著播放，不把畫面搶回去；在文字框裡打字用的
 * 空白鍵與方向鍵不算捲動。用快捷鍵換到的片段（reveal）不在看得到的範圍時捲到看得到。
 *
 * @param {{
 *   segments: any[],
 *   visible: number[],
 *   currentIndex: number,
 *   reveal: { index: number } | null,
 *   emptyText: string,
 *   activeSet: Set<number>,
 *   activeWords: Map<number, number>,
 *   followIndex: number,
 *   following: boolean,
 *   canPlay: boolean,
 *   onUserScroll: () => void,
 *   onSeek: (seconds: number) => void,
 *   editing: import("@/utils/segmentCorrections").Editing | null,
 *   saves: import("@/utils/segmentCorrections").Saves,
 *   actions: import("./correction-view").RowActions,
 * }} props
 */
export function SegmentList({
    segments, visible, currentIndex, reveal, emptyText,
    activeSet, activeWords, followIndex, following, canPlay, onUserScroll, onSeek, editing, saves, actions,
}) {
    const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null))
    /** 片段在 segments 裡的位置 → 在列表裡的第幾列；篩選掉的不在裡面。 */
    const rowOf = useMemo(() => new Map(visible.map((index, row) => [index, row])), [visible])
    const editingIndex = useMemo(() => {
        if (!editing) return -1
        return rowOf.get(segments.findIndex((s) => s.seg_key === editing.segKey)) ?? -1
    }, [segments, editing, rowOf])
    const rangeExtractor = useCallback((range) => {
        const indexes = defaultRangeExtractor(range)
        if (editingIndex < 0 || indexes.includes(editingIndex)) return indexes
        return [...indexes, editingIndex].sort((a, b) => a - b)
    }, [editingIndex])
    // eslint-disable-next-line react-hooks/incompatible-library -- 列表自己決定哪幾列要重畫，這裡不需要 React Compiler 幫忙記住
    const virtualizer = useVirtualizer({
        count: visible.length,
        getScrollElement: () => containerRef.current,
        estimateSize: () => 43,
        overscan: 8,
        getItemKey: (row) => segments[visible[row]].seg_key,
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

    const followRow = rowOf.get(followIndex) ?? -1
    useEffect(() => {
        const container = containerRef.current
        if (!following || followRow < 0 || !container) return
        if (!fullyVisible(container, followRow)) virtualizer.scrollToIndex(followRow, { align: "center" })
    }, [following, followRow, virtualizer])

    // 用快捷鍵換到的片段：捲到看得到就好，不搶到中間。跟著播放的捲動會捲到同一列時交給它，免得捲兩次
    useEffect(() => {
        const container = containerRef.current
        const row = reveal ? rowOf.get(reveal.index) ?? -1 : -1
        if (row < 0 || !container || (following && reveal.index === followIndex)) return
        if (!fullyVisible(container, row)) virtualizer.scrollToIndex(row, { align: "auto" })
        // 只在換片段（reveal 換了一個新的）時捲；列表內容變了不再捲一次
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reveal])

    return (
        <div
            ref={containerRef}
            tabIndex={0}
            aria-label="片段列表"
            // 撐滿外層（position: relative 的那一格）：高度不靠百分比，外層的高度由 flex 算出來，
            // 列表才有固定的高度、只畫看得到的那幾列
            style={{ position: "absolute", inset: 0, overflowY: "auto", outline: "none" }}
        >
            {!visible.length && (
                <div style={{ padding: "48px 16px", color: "#8888a8", fontSize: 13, textAlign: "center" }}>{emptyText}</div>
            )}
            <div style={{ position: "relative", width: "100%", height: virtualizer.getTotalSize() }}>
                {virtualizer.getVirtualItems().map((item) => {
                    const index = visible[item.index]
                    const segment = segments[index]
                    return (
                        <div
                            key={item.key}
                            data-index={item.index}
                            ref={virtualizer.measureElement}
                            style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${item.start}px)` }}
                        >
                            <SegmentRow
                                segment={segment}
                                active={activeSet.has(index)}
                                current={index === currentIndex}
                                activeWord={activeWords.get(index) ?? -1}
                                canPlay={canPlay}
                                onSeek={onSeek}
                                editing={item.index === editingIndex ? editing : null}
                                save={saves[segment.seg_key]}
                                actions={actions}
                            />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
