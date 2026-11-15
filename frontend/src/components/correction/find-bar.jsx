import { useEffect, useRef, useState } from "react"
import { Button, Input, Popconfirm } from "antd"
import { ChevronDown, ChevronUp, Search, X } from "lucide-react"
import { findKeyAction, replaceConfirmText } from "@/utils/segmentSearch"

/** @type {import("react").CSSProperties} */
const BAR_STYLE = {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    padding: "8px 16px",
    borderTop: "1px solid #2a2a48",
    background: "#1a1a34",
    flexShrink: 0,
}

/** @type {import("react").CSSProperties} */
const COUNT_STYLE = { minWidth: 96, color: "#8888a8", fontSize: 12, whiteSpace: "nowrap" }

/** 符合的片段數，例如「2／5 個片段」；沒有要找的字時不寫。 */
function countText(query, total, current) {
    if (!query) return ""
    if (!total) return "沒有符合的片段"
    return `${current + 1}／${total} 個片段`
}

/**
 * 校正頁的尋找與全部取代（#356）。在校正頁按 Ctrl+F 打開（片段列表只畫看得到的那幾列，瀏覽器內建的尋找找不到
 * 沒畫出來的片段）。
 *
 * - 尋找框裡 Enter 下一個、Shift+Enter 上一個、Esc 收起來；寫出符合的片段數與現在是第幾個。
 * - 全部取代之前先寫明會改到幾個片段、一共幾處，確認之後才做；取代之後內容都和現在相同時不能按。
 *
 * @param {{
 *   search: ReturnType<typeof import("@/hooks/useSegmentSearch").useSegmentSearch>,
 *   onReplaceAll: (find: string, replacement: string) => Promise<unknown>,
 *   onClose: () => void,
 * }} props
 */
export function FindBar({ search, onReplaceAll, onClose }) {
    const { query, replacement, matches, currentIndex, plan, focusRequest, actions } = search
    const inputRef = useRef(/** @type {import("antd").InputRef | null} */ (null))
    const [replacing, setReplacing] = useState(false)

    // 打開時與再按一次 Ctrl+F 時，焦點放進尋找框並選起原本的字，直接打就是新的要找的字
    useEffect(() => {
        inputRef.current?.focus({ cursor: "all" })
    }, [focusRequest])

    const onFindKeyDown = (event) => {
        const action = findKeyAction({
            key: event.key,
            shiftKey: event.shiftKey,
            isComposing: event.nativeEvent.isComposing,
            keyCode: event.keyCode,
        })
        if (!action) return
        event.preventDefault()
        if (action === "close") onClose()
        else actions.step(action)
    }

    const replaceAll = async () => {
        setReplacing(true)
        try {
            await onReplaceAll(query, replacement)
        } finally {
            setReplacing(false)
        }
    }

    const total = matches.length
    const changes = plan?.segments ?? 0
    let replaceTitle
    if (!query) replaceTitle = "先輸入要找的文字"
    else if (!total) replaceTitle = "沒有符合的片段"
    else if (!changes) replaceTitle = "取代之後內容都和現在相同"

    return (
        <div role="search" aria-label="尋找與取代" style={BAR_STYLE}>
            <Input
                ref={inputRef}
                size="small"
                aria-label="尋找"
                placeholder="尋找"
                prefix={<Search size={14} color="#8888a8" />}
                value={query}
                onChange={(event) => actions.setQuery(event.target.value)}
                onKeyDown={onFindKeyDown}
                style={{ width: 200 }}
            />
            <span aria-live="polite" style={COUNT_STYLE}>{countText(query, total, currentIndex)}</span>
            <Button
                size="small"
                type="text"
                aria-label="上一個符合的片段"
                title="上一個符合的片段（Shift+Enter）"
                icon={<ChevronUp size={14} />}
                disabled={!total}
                onClick={() => actions.step("previous")}
            />
            <Button
                size="small"
                type="text"
                aria-label="下一個符合的片段"
                title="下一個符合的片段（Enter）"
                icon={<ChevronDown size={14} />}
                disabled={!total}
                onClick={() => actions.step("next")}
            />
            <Input
                size="small"
                aria-label="取代為"
                placeholder="取代為"
                value={replacement}
                onChange={(event) => actions.setReplacement(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === "Escape" && !event.nativeEvent.isComposing) onClose()
                }}
                style={{ width: 200 }}
            />
            <Popconfirm
                title="全部取代？"
                description={(
                    <div style={{ maxWidth: 320 }}>
                        <div style={{ overflowWrap: "anywhere" }}>
                            把「{query}」{replacement ? `換成「${replacement}」` : "換成空的"}。
                        </div>
                        <div>{plan && replaceConfirmText(plan)}</div>
                        <div style={{ color: "#8888a8" }}>做完可以按「復原」整批收回。</div>
                    </div>
                )}
                okText="全部取代"
                cancelText="取消"
                disabled={!changes || replacing}
                onConfirm={replaceAll}
            >
                <Button size="small" disabled={!changes} loading={replacing} title={replaceTitle}>
                    全部取代
                </Button>
            </Popconfirm>
            <Button
                size="small"
                type="text"
                aria-label="關閉尋找"
                title="關閉尋找（Esc）"
                icon={<X size={14} />}
                onClick={onClose}
                style={{ marginLeft: "auto", color: "#8888a8" }}
            />
        </div>
    )
}
