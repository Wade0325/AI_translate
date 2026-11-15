import { Dropdown } from "antd"
import { ChevronDown } from "lucide-react"
import { NO_SPEAKER_LABEL, speakerChoices } from "@/utils/speakers"

/** 說話者編號（S0、S1…）的顏色：照編號輪流用，同一位說話者在整份裡顏色不變。 */
const SPEAKER_COLORS = ["#2dd4a8", "#d4a72d", "#47b8d4", "#e07a9f", "#8b5cf6", "#e0884f", "#7fc97f", "#c9c95c"]

function speakerColor(speaker) {
    const n = Number(/\d+/.exec(speaker)?.[0] ?? 0)
    return SPEAKER_COLORS[n % SPEAKER_COLORS.length]
}

/** @type {import("react").CSSProperties} */
const BUTTON_STYLE = {
    display: "inline-flex",
    alignItems: "center",
    gap: 2,
    flexShrink: 0,
    minWidth: 28,
    padding: 0,
    border: 0,
    background: "none",
    fontSize: 12,
    fontWeight: 600,
    lineHeight: "26px",
    whiteSpace: "nowrap",
}

/**
 * 這個任務每位說話者的片段數與新的說話者編號：片段列的說話者選單用（#354）。
 *
 * @typedef {{ speakers: string[], counts: Map<string | null, number>, nextSpeaker: string }} SpeakerInfo
 */

/**
 * 片段列的說話者（#354）：點開是選單，可以把這個片段改成現有的另一位或新的說話者；這位說話者（或沒有說話者）
 * 的片段不只一個時，另外可以把它們全部換成另一位，一次操作，可以整批復原。
 *
 * @param {{
 *   segKey: string,
 *   speaker: string | null,
 *   info: SpeakerInfo,
 *   disabled: boolean,
 *   actions: { setSpeaker: (segKey: string, speaker: string) => void,
 *              reassignSpeaker: (from: string | null, to: string) => void },
 * }} props
 */
export function SpeakerMenu({ segKey, speaker, info, disabled, actions }) {
    const choices = speakerChoices(info.speakers, speaker, info.nextSpeaker)
    const count = info.counts.get(speaker) ?? 0
    const label = (choice) => (choice.isNew ? `新的說話者（${choice.speaker}）` : choice.speaker)
    const choiceItems = (scope) => choices.map((choice) => ({ key: `${scope}:${choice.speaker}`, label: label(choice) }))
    /** @type {NonNullable<import("antd").MenuProps["items"]>} */
    const items = [{ type: "group", label: "這個片段改成", children: choiceItems("one") }]
    if (count > 1) {
        const source = speaker ? `${speaker} 的` : `${NO_SPEAKER_LABEL}的`
        items.push(
            { type: "divider" },
            { type: "group", label: `${source} ${count} 個片段全部換成`, children: choiceItems("all") },
        )
    }
    const onClick = ({ key }) => {
        const [scope, to] = key.split(":")
        if (scope === "one") actions.setSpeaker(segKey, to)
        else actions.reassignSpeaker(speaker, to)
    }

    return (
        <Dropdown menu={{ items, onClick }} trigger={["click"]} disabled={disabled}>
            <button
                type="button"
                className="correction-speaker"
                title={disabled ? undefined : "改說話者"}
                style={{
                    ...BUTTON_STYLE,
                    color: speaker ? speakerColor(speaker) : "#686888",
                    cursor: disabled ? "default" : "pointer",
                }}
            >
                {speaker || "未指定"}
                {!disabled && <ChevronDown size={11} />}
            </button>
        </Dropdown>
    )
}
