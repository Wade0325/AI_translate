import { Tooltip, Typography } from "antd"

const { Text } = Typography

/** 欄位停用的原因，例如所選的模型不支援這項輸入；沒有原因時不顯示。 */
export function ReasonText({ reason, style }) {
    if (!reason) return null
    return <Text style={{ fontSize: 10, color: "#d4a72d", ...style }}>{reason}</Text>
}

/**
 * 包得住停用按鈕的 Tooltip：停用的按鈕收不到滑鼠事件，外面包一層 span 才顯示得出原因。
 * title 是 null 時不顯示。
 */
export function ReasonTooltip({ title, children }) {
    return (
        <Tooltip title={title}>
            <span style={{ display: "inline-flex" }}>{children}</span>
        </Tooltip>
    )
}
