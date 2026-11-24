import { Button, Popconfirm, Segmented } from "antd"
import { CheckCheck } from "lucide-react"
import { keepEditorFocus } from "@/utils/segmentCorrections"
import { ShortcutHelp } from "./shortcut-help"

/** @type {import("react").CSSProperties} */
const BAR_STYLE = {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    padding: "8px 16px",
    borderBottom: "1px solid #2a2a48",
    flexShrink: 0,
}

/** 「只看說話者不確定的」的說明。 */
const UNSURE_TITLE = "模型拿不定是誰說的、還沒看過的片段。先聽這幾句：說話者對就按 V，不對就點說話者改。模型很有把握卻標錯的片段不會列在這裡"

/**
 * 片段列表上方的工具列（#349）：篩選（全部、只看待查的、只看還沒看過的，任務有說話者機率時另有只看說話者不確定的）、
 * 其餘全部標成已確認，以及快捷鍵說明。
 *
 * 其餘全部標成已確認按下去之前先問一次，寫明會標幾個片段；確認的框打開時（confirmOpen）頁面的快捷鍵暫停，
 * 免得在框裡按的鍵動到列表。工具列的按鈕用滑鼠按時不拿走焦點：焦點留在按鈕上時，空白鍵與 Enter 會再按一次那個
 * 按鈕，不是播放與開始改。
 *
 * @param {{
 *   filter: import("@/utils/reviewStates").ReviewFilter,
 *   counts: Record<import("@/utils/reviewStates").ReviewFilter, number>,
 *   onFilter: (filter: import("@/utils/reviewStates").ReviewFilter) => void,
 *   offersUnsure: boolean,
 *   withoutReviewState: number,
 *   bulkPending: boolean,
 *   confirmOpen: boolean,
 *   onConfirmOpen: (open: boolean) => void,
 *   onMarkRestVerified: () => void,
 * }} props
 */
export function ReviewToolbar({
    filter, counts, onFilter, offersUnsure, withoutReviewState, bulkPending, confirmOpen, onConfirmOpen,
    onMarkRestVerified,
}) {
    const options = [
        { value: "all", label: `全部 ${counts.all}` },
        { value: "flagged", label: `只看待查的 ${counts.flagged}` },
        { value: "unseen", label: `只看還沒看過的 ${counts.unseen}` },
    ]
    if (offersUnsure) options.push({ value: "unsure", label: `只看說話者不確定的 ${counts.unsure}`, title: UNSURE_TITLE })
    return (
        <div role="toolbar" aria-label="篩選與確認狀態" style={BAR_STYLE}>
            <Segmented
                size="small"
                aria-label="篩選片段"
                value={filter}
                onChange={(value) => onFilter(/** @type {import("@/utils/reviewStates").ReviewFilter} */ (value))}
                options={options}
            />
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                <Popconfirm
                    open={confirmOpen}
                    placement="bottomRight"
                    onOpenChange={(open) => onConfirmOpen(open && withoutReviewState > 0)}
                    title={`把其餘 ${withoutReviewState} 個片段標成已確認？`}
                    description="還沒有確認狀態的片段都會標成已確認，已經標成待查的不動。做完可以馬上復原。"
                    okText="標成已確認"
                    cancelText="取消"
                    onConfirm={() => {
                        onConfirmOpen(false)
                        onMarkRestVerified()
                    }}
                    onCancel={() => onConfirmOpen(false)}
                >
                    <Button
                        size="small"
                        icon={<CheckCheck size={14} />}
                        disabled={!withoutReviewState}
                        loading={bulkPending}
                        onMouseDown={keepEditorFocus}
                    >
                        其餘全部標成已確認
                    </Button>
                </Popconfirm>
                <ShortcutHelp />
            </div>
        </div>
    )
}
