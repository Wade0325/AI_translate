import { useLayoutEffect, useRef, useState } from "react"
import { editingKeyAction } from "@/utils/segmentEditing"

/** 文字框照內容長高，不出現捲軸：和原本那一列的文字一樣高。 */
function fitHeight(textarea) {
    textarea.style.height = "auto"
    textarea.style.height = `${textarea.scrollHeight}px`
}

/** @type {import("react").CSSProperties} */
const EDITOR_STYLE = {
    display: "block",
    width: "100%",
    margin: "-1px 0",
    padding: "0 6px",
    border: "1px solid #2dd4a8",
    borderRadius: 4,
    background: "#14142a",
    color: "#e8e8e8",
    font: "inherit",
    fontSize: 14,
    lineHeight: "24px",
    resize: "none",
    overflow: "hidden",
    outline: "none",
}

/**
 * 改一個片段的文字（#348）：點片段的文字換成這個文字框，游標放在點的地方。
 *
 * 按 Enter 或點到別處就存（onSave），按 Esc 放棄（onCancel）；輸入法選字時按的 Enter 與 Esc 交給輸入法。
 * Tab 播放或暫停、Shift+Tab 倒退 3 秒（onPlayback），焦點留在文字框裡。空白鍵與方向鍵照常是打字用的。
 * 切到別的視窗不算點到別處：回來時照樣在改。
 *
 * @param {{
 *   initialText: string,
 *   selection: { start: number, end: number } | null,
 *   onSave: (draft: string) => void,
 *   onCancel: () => void,
 *   onPlayback: (action: "toggle-playback" | "rewind") => void,
 * }} props
 */
export function SegmentEditor({ initialText, selection, onSave, onCancel, onPlayback }) {
    const [draft, setDraft] = useState(initialText)
    // 打開時的游標位置只用一次，之後游標由使用者移動
    const [initialSelection] = useState(selection)
    const ref = useRef(/** @type {HTMLTextAreaElement | null} */ (null))
    // 存或放棄之後就結束了：之後文字框被拿掉時的 blur 不再存一次
    const finished = useRef(false)

    useLayoutEffect(() => {
        const textarea = ref.current
        if (!textarea) return
        fitHeight(textarea)
        textarea.focus({ preventScroll: true })
        const length = textarea.value.length
        const start = Math.min(initialSelection?.start ?? length, length)
        const end = Math.min(initialSelection?.end ?? start, length)
        textarea.setSelectionRange(start, end)
    }, [initialSelection])

    const finish = (done) => {
        if (finished.current) return
        finished.current = true
        done()
    }

    const onKeyDown = (event) => {
        const action = editingKeyAction({
            key: event.key,
            shiftKey: event.shiftKey,
            ctrlKey: event.ctrlKey,
            altKey: event.altKey,
            metaKey: event.metaKey,
            isComposing: event.nativeEvent.isComposing,
            keyCode: event.keyCode,
        })
        if (!action) return
        // Enter 不換行；Tab 與 Shift+Tab 不把焦點移到下一個元素
        event.preventDefault()
        if (action === "save") finish(() => onSave(draft))
        else if (action === "cancel") finish(onCancel)
        else onPlayback(action)
    }

    const onBlur = () => {
        // 切到別的視窗或分頁時文字框也會 blur，這時不存：回來時焦點回到文字框，照樣在改
        if (!document.hasFocus()) return
        finish(() => onSave(draft))
    }

    return (
        <textarea
            ref={ref}
            aria-label="片段的文字"
            className="correction-editor"
            rows={1}
            value={draft}
            spellCheck={false}
            onChange={(event) => {
                setDraft(event.target.value)
                fitHeight(event.target)
            }}
            onKeyDown={onKeyDown}
            onBlur={onBlur}
            style={EDITOR_STYLE}
        />
    )
}
