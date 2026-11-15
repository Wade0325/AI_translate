import { Button, Popover } from "antd"
import { Keyboard } from "lucide-react"
import { SHORTCUT_GROUPS } from "@/utils/correctionShortcuts"
import { keepEditorFocus } from "@/utils/segmentCorrections"

/** @type {import("react").CSSProperties} */
const KEY_STYLE = {
    display: "inline-block",
    minWidth: 22,
    padding: "0 6px",
    border: "1px solid #3a3a5c",
    borderBottomWidth: 2,
    borderRadius: 4,
    background: "#1a1a34",
    color: "#e8e8e8",
    fontSize: 12,
    lineHeight: "20px",
    textAlign: "center",
    whiteSpace: "nowrap",
}

function ShortcutList() {
    return (
        <div aria-label="快捷鍵說明" style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 380 }}>
            {SHORTCUT_GROUPS.map((group) => (
                <section key={group.title}>
                    <div style={{ color: "#8888a8", fontSize: 12, marginBottom: 6 }}>{group.title}</div>
                    <table style={{ borderCollapse: "collapse" }}>
                        <tbody>
                            {group.items.map((item) => (
                                <tr key={item.label}>
                                    <td style={{ width: 96, padding: "3px 12px 3px 0", whiteSpace: "nowrap", verticalAlign: "top" }}>
                                        {item.keys.map((k, i) => (
                                            <span key={k}>
                                                {i > 0 && <span style={{ color: "#686888", margin: "0 3px" }}>、</span>}
                                                <kbd style={KEY_STYLE}>{k}</kbd>
                                            </span>
                                        ))}
                                    </td>
                                    <td style={{ padding: "3px 0", color: "#e8e8e8", fontSize: 13, lineHeight: "20px" }}>{item.label}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>
            ))}
        </div>
    )
}

/**
 * 頁面上列出快捷鍵的地方（#349）：按「快捷鍵」打開，列出不在打字時與打字時的鍵。內容照 SHORTCUT_GROUPS，
 * 和實際的對應同一份。
 */
export function ShortcutHelp() {
    return (
        <Popover content={<ShortcutList />} trigger="click" placement="bottomRight" title="快捷鍵">
            {/* 用滑鼠按時不拿走焦點：焦點留在按鈕上時，空白鍵會再按一次這個按鈕，不是播放 */}
            <Button size="small" icon={<Keyboard size={14} />} onMouseDown={keepEditorFocus}>快捷鍵</Button>
        </Popover>
    )
}
