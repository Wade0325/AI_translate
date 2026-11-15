import { useEffect, useMemo, useState } from "react"
import { Button, Tag } from "antd"
import { formatRecordTime, historyEntries, valueLabel } from "@/utils/correctionHistory"
import { saveFailureMessage } from "@/utils/segmentCorrections"

/** @type {import("react").CSSProperties} */
const PANEL_STYLE = {
    marginTop: 6,
    padding: "6px 10px",
    borderRadius: 4,
    background: "#1a1a34",
    border: "1px solid #2a2a48",
}

/** @type {import("react").CSSProperties} */
const ENTRY_STYLE = { display: "flex", alignItems: "flex-start", gap: 8, padding: "6px 0", borderTop: "1px solid #2a2a48" }

/** @type {import("react").CSSProperties} */
const META_STYLE = { display: "flex", flexWrap: "wrap", alignItems: "center", columnGap: 6, rowGap: 2, color: "#8888a8", fontSize: 12, lineHeight: "20px" }

/** @type {import("react").CSSProperties} */
const VALUE_STYLE = { color: "#b8b8d0", fontSize: 13, lineHeight: "22px", overflowWrap: "anywhere" }

const TAG_STYLE = { marginInlineEnd: 0, fontSize: 11, lineHeight: "18px" }

const FIELD_LABELS = { text: "文字", speaker: "說話者" }

/**
 * 一筆校正紀錄的改前與改後：說話者寫在一行（S0 → S1），文字分兩行。
 *
 * @param {{ entry: import("@/utils/correctionHistory").RecordEntry }} props
 */
function RecordChange({ entry }) {
    const before = valueLabel(entry.field, entry.before)
    const after = valueLabel(entry.field, entry.after)
    if (entry.field === "speaker") {
        return <div style={VALUE_STYLE}>{before} → {after}</div>
    }
    return (
        <>
            <div style={{ ...VALUE_STYLE, color: "#8888a8" }}>
                <span style={{ marginRight: 6, fontSize: 12 }}>改前</span>{before}
            </div>
            <div style={VALUE_STYLE}>
                <span style={{ marginRight: 6, fontSize: 12, color: "#8888a8" }}>改後</span>{after}
            </div>
        </>
    )
}

/**
 * 片段的歷程（#355）：展開「校正過」（或「歷程」）時列出這個片段的每一筆校正紀錄，最上面是最新的一筆，最下面是
 * 原始轉錄，每一版都有「回到這一版」。文字與說話者各自最新的一筆標「現在」；其他和現在的內容相同的版本標
 * 「和現在相同」，按鈕不能按（送出也不會記任何一筆）。
 *
 * - 回到某一版是再記一筆校正紀錄，之前的都留著，所以回去之後還能再回來；存完一樣出現「已存檔，復原」。
 * - 屬於整批操作（全部取代、把這位說話者全部換成另一位）的那一筆標出來，寫明那次一共改了幾個片段，可以整批復原；
 *   之後又改過的片段略過，結果寫在頁面上方。
 * - 片段的內容一變（存了一次校正、復原、整批復原）就重新讀一次，新的一筆馬上出現在最上面。
 *
 * @param {{
 *   segment: import("@/utils/segmentCorrections").Segment,
 *   saving: boolean,
 *   actions: import("./correction-view").RowActions,
 *   onButtonMouseDown?: (event: { preventDefault: () => void }) => void,
 * }} props
 */
export function SegmentHistory({ segment, saving, actions, onButtonMouseDown }) {
    const [loaded, setLoaded] = useState(/** @type {{
        history: import("@/utils/correctionHistory").SegmentCorrectionRecords | null, error: unknown,
    }} */ ({ history: null, error: null }))
    const [attempt, setAttempt] = useState(0)
    const [undoing, setUndoing] = useState(false)

    useEffect(() => {
        let current = true
        actions.correctionRecords(segment.seg_key)
            .then((history) => current && setLoaded({ history, error: null }))
            // 讀不到時留著上一次讀到的，另外寫原因
            .catch((error) => current && setLoaded((last) => ({ history: last.history, error })))
        return () => {
            current = false
        }
    }, [actions, segment, attempt])

    const entries = useMemo(
        () => (loaded.history ? historyEntries(loaded.history, segment) : null),
        [loaded.history, segment],
    )
    const busy = saving || undoing

    const undoBulk = async (operationId) => {
        setUndoing(true)
        try {
            await actions.undoBulk(operationId)
        } finally {
            setUndoing(false)
        }
    }

    const recordCount = loaded.history?.records.length ?? 0
    return (
        <section aria-label="這個片段的歷程" style={PANEL_STYLE}>
            <div style={{ color: "#8888a8", fontSize: 12, lineHeight: "20px", paddingBottom: 4 }}>
                歷程{loaded.history && `：${recordCount} 筆校正，最上面是最新的`}
            </div>
            {loaded.error && (
                <div role="alert" style={{ display: "flex", alignItems: "center", columnGap: 4, color: "#ff7875", fontSize: 12, lineHeight: "24px" }}>
                    <span>讀不到歷程：{saveFailureMessage(loaded.error)}</span>
                    <Button size="small" type="link" onMouseDown={onButtonMouseDown} onClick={() => setAttempt((n) => n + 1)}>重試</Button>
                </div>
            )}
            {!entries && !loaded.error && <div style={{ color: "#8888a8", fontSize: 12, lineHeight: "24px" }}>讀取中…</div>}
            {entries && (
                <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
                    {entries.map((entry) => (
                        <li key={entry.key} style={ENTRY_STYLE}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={META_STYLE}>
                                    {entry.kind === "original" ? (
                                        <span style={{ color: "#b8b8d0" }}>原始轉錄</span>
                                    ) : (
                                        <>
                                            <span>{formatRecordTime(entry.createdAt)}</span>
                                            <span style={{ color: "#b8b8d0" }}>改了{FIELD_LABELS[entry.field]}</span>
                                            {entry.bulk && (
                                                <Tag style={{ ...TAG_STYLE, color: "#47b8d4", borderColor: "#47b8d480" }}>
                                                    整批操作：一共改了 {entry.segmentCount} 個片段
                                                </Tag>
                                            )}
                                        </>
                                    )}
                                    {entry.current && <Tag color="green" style={TAG_STYLE}>現在</Tag>}
                                    {!entry.current && !entry.request && <Tag style={TAG_STYLE}>和現在相同</Tag>}
                                </div>
                                {entry.kind === "original" ? (
                                    <div style={VALUE_STYLE}>
                                        {/* 沒有說話者的任務不寫；現在有說話者、原始轉錄沒有時才寫出來 */}
                                        {(entry.speaker || segment.speaker) && (
                                            <span style={{ marginRight: 8, fontWeight: 600 }}>{valueLabel("speaker", entry.speaker)}</span>
                                        )}
                                        {entry.text || "（沒有文字）"}
                                    </div>
                                ) : (
                                    <RecordChange entry={entry} />
                                )}
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                                <Button
                                    size="small"
                                    disabled={busy || !entry.request}
                                    title={entry.request ? undefined : "現在已經是這一版"}
                                    onMouseDown={onButtonMouseDown}
                                    onClick={() => actions.returnTo(segment.seg_key, entry.request)}
                                >
                                    回到這一版
                                </Button>
                                {entry.kind === "record" && entry.bulk && (
                                    <Button
                                        size="small"
                                        disabled={busy}
                                        title={`復原這次操作改到的 ${entry.segmentCount} 個片段；之後又改過的片段略過`}
                                        onMouseDown={onButtonMouseDown}
                                        onClick={() => undoBulk(entry.operationId)}
                                    >
                                        整批復原
                                    </Button>
                                )}
                            </div>
                        </li>
                    ))}
                </ol>
            )}
        </section>
    )
}
