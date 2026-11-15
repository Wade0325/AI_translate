import { Dropdown } from "antd"
import { ChevronDown } from "lucide-react"
import { choiceLabel, sentence, speakerChoices, speakerText } from "@/utils/speakers"

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
 * 說話者那一格的提示：取了名字的說話者另外寫出它的說話者編號。
 *
 * @param {string | null} speaker
 * @param {import("@/utils/speakers").SpeakerNames} names
 */
function buttonTitle(speaker, names) {
    if (!speaker) return "改說話者"
    return names[speaker] ? `${speaker}：改說話者或名字` : "改說話者或取名字"
}

/**
 * 這個任務每位說話者的片段數、新的說話者編號（#354）與說話者名稱（#359）：片段列的說話者選單用。
 *
 * @typedef {{ speakers: string[], counts: Map<string | null, number>, nextSpeaker: string,
 *   names: import("@/utils/speakers").SpeakerNames }} SpeakerInfo
 */

/**
 * 片段列的說話者（#354）：點開是選單，可以把這個片段改成現有的另一位或新的說話者；這位說話者（或沒有說話者）
 * 的片段不只一個時，另外可以把它們全部換成另一位，一次操作，可以整批復原。
 *
 * 取了說話者名稱的說話者寫名稱（#359）。選單最上面是「替 S0 取名字」（取了名字的是「改 S0 的名字」），交給
 * actions.startRenaming 打開取名字的對話框；對話框放在校正頁，不放在這一列：列表只畫看得到的列，這一列被捲走時
 * 對話框才不會跟著不見。沒有說話者的片段不能取名字。
 *
 * @param {{
 *   segKey: string,
 *   speaker: string | null,
 *   info: SpeakerInfo,
 *   disabled: boolean,
 *   actions: { setSpeaker: (segKey: string, speaker: string) => void,
 *              reassignSpeaker: (from: string | null, to: string) => void,
 *              startRenaming: (speaker: string) => void },
 * }} props
 */
export function SpeakerMenu({ segKey, speaker, info, disabled, actions }) {
    const choices = speakerChoices(info.speakers, speaker, info.nextSpeaker)
    const count = info.counts.get(speaker) ?? 0
    const choiceItems = (scope) => choices.map((choice) => ({
        key: `${scope}:${choice.speaker}`, label: choiceLabel(choice, info.names),
    }))
    /** @type {NonNullable<import("antd").MenuProps["items"]>} */
    const items = []
    if (speaker) {
        const renameLabel = info.names[speaker] ? `改 ${speaker} 的名字…` : `替 ${speaker} 取名字…`
        items.push({ key: "rename", label: renameLabel }, { type: "divider" })
    }
    items.push({ type: "group", label: "這個片段改成", children: choiceItems("one") })
    if (count > 1) {
        const label = sentence(speakerText(speaker, info.names), "的", count, "個片段全部換成")
        items.push({ type: "divider" }, { type: "group", label, children: choiceItems("all") })
    }
    const onClick = ({ key }) => {
        if (key === "rename") {
            if (speaker) actions.startRenaming(speaker)
            return
        }
        const [scope, to] = key.split(":")
        if (scope === "one") actions.setSpeaker(segKey, to)
        else actions.reassignSpeaker(speaker, to)
    }

    return (
        <Dropdown menu={{ items, onClick }} trigger={["click"]} disabled={disabled}>
            <button
                type="button"
                className="correction-speaker"
                title={disabled ? undefined : buttonTitle(speaker, info.names)}
                style={{
                    ...BUTTON_STYLE,
                    color: speaker ? speakerColor(speaker) : "#686888",
                    cursor: disabled ? "default" : "pointer",
                }}
            >
                {speakerText(speaker, info.names)}
                {!disabled && <ChevronDown size={11} />}
            </button>
        </Dropdown>
    )
}
