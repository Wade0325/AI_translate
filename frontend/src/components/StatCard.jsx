import { Card } from "antd"

/** 統計卡片：Dashboard / History / Billing 共用同一外觀。 */
export function StatCard({ title, value, subtitle, icon: Icon, iconColor, bgColor, valueColor = "#e8e8e8" }) {
    return (
        <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 20 } }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                    <div style={{ color: "#8888a8", fontSize: 13, marginBottom: 8 }}>{title}</div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: valueColor }}>{value}</div>
                    {subtitle && (
                        <div style={{ color: "#8888a8", fontSize: 12, marginTop: 4 }}>{subtitle}</div>
                    )}
                </div>
                <div style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: bgColor,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                }}>
                    <Icon size={16} color={iconColor} />
                </div>
            </div>
        </Card>
    )
}
