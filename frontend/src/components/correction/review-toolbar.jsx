import { Button, Popconfirm, Segmented } from "antd"
import { CheckCheck } from "lucide-react"
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

/**
 * 片段列表上方的工具列（#349）：篩選（全部、只看待查的、只看還沒看過的）、其餘全部標成已確認，以及快捷鍵說明。
 *
 * 其餘全部標成已確認按下去之前先問一次，寫明會標幾個片段；確認的框打開時（confirmOpen）頁面的快捷鍵暫停，
 * 免得在框裡按的鍵動到列表。
 *
 * @param {{
 *   filter: import("@/utils/reviewStates").ReviewFilter,
 *   counts: Record<import("@/utils/reviewStates").ReviewFilter, number>,
 *   onFilter: (filter: import("@/utils/reviewStates").ReviewFilter) => void,
 *   unreviewed: number,
 *   bulkPending: boolean,
 *   confirmOpen: boolean,
 *   onConfirmOpen: (open: boolean) => void,
 *   onMarkRestVerified: () => void,
 * }} props
 */
export function ReviewToolbar({ filter, counts, onFilter, unreviewed, bulkPending, confirmOpen, onConfirmOpen, onMarkRestVerified }) {
    return (
        <div role="toolbar" aria-label="篩選與確認狀態" style={BAR_STYLE}>
            <Segmented
                size="small"
                aria-label="篩選片段"
                value={filter}
                onChange={(value) => onFilter(/** @type {import("@/utils/reviewStates").ReviewFilter} */ (value))}
                options={[
                    { value: "all", label: `全部 ${counts.all}` },
                    { value: "flagged", label: `只看待查的 ${counts.flagged}` },
                    { value: "unseen", label: `只看還沒看過的 ${counts.unseen}` },
                ]}
            />
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                <Popconfirm
                    open={confirmOpen}
                    onOpenChange={(open) => onConfirmOpen(open && unreviewed > 0)}
                    title={`把其餘 ${unreviewed} 個片段標成已確認？`}
                    description="還沒有確認狀態的片段都會標成已確認，已經標成待查的不動。做完可以馬上復原。"
                    okText="標成已確認"
                    cancelText="取消"
                    onConfirm={() => {
                        onConfirmOpen(false)
                        onMarkRestVerified()
                    }}
                    onCancel={() => onConfirmOpen(false)}
                >
                    <Button size="small" icon={<CheckCheck size={14} />} disabled={!unreviewed} loading={bulkPending}>
                        其餘全部標成已確認
                    </Button>
                </Popconfirm>
                <ShortcutHelp />
            </div>
        </div>
    )
}
