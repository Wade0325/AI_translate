import { Typography } from "antd"
import { Link } from "react-router-dom"
import { describeConnection } from "@/utils/connectionLoss"

const { Text } = Typography

/**
 * 送出任務之後連線斷了（轉錄頁的檔案卡用）：原因與下一步，連不上伺服器時另附前往查看的連結。
 * connection 是檔案卡記下的連線狀況（utils/connectionLoss.js 的 CONNECTION）。任務可能還在跑，
 * 所以用提醒的顏色，不用失敗的紅色。
 */
export function ConnectionNotice({ connection }) {
    const shown = describeConnection(connection)
    if (!shown) return null
    return (
        <div
            data-testid="connection-notice"
            style={{
                borderTop: "1px solid rgba(212, 167, 45, 0.2)",
                background: "rgba(212, 167, 45, 0.06)",
                padding: "8px 12px 10px 56px",
                display: "flex",
                flexDirection: "column",
                gap: 4,
            }}
        >
            <Text style={{ fontSize: 12, fontWeight: 500, color: "#e0b84a" }}>{shown.reason}</Text>
            <Text style={{ fontSize: 12, color: "#c8c8d8" }}>
                {shown.nextStep}
                {shown.links.map((link) => (
                    <Link key={link.to} to={link.to} style={{ marginLeft: 8 }}>{link.label}</Link>
                ))}
            </Text>
        </div>
    )
}
