import { Button, Space, Typography } from "antd"
import { Link } from "react-router-dom"

const { Text } = Typography

/**
 * 轉錄頁選本機時，這台電腦能不能轉錄（#11）：不能時寫出原因與下一步，顯卡記憶體不足時提示。
 * view 來自 utils/localReadiness.js 的 readinessView；alternative 是建議改用的供應商
 * { value, label }（utils/providerList.js 的 alternativeProvider），按了才切換（Q1）。
 * 沒有要說的時不顯示。
 */
export function LocalReadinessNotice({ view, alternative, onSwitch }) {
    if (!view.blockedReason && !view.warning) return null
    return (
        <Space direction="vertical" size={4}>
            {view.blockedReason && (
                <Space size={8} wrap>
                    <Text style={{ fontSize: 12, color: "#d46a2d" }}>{view.blockedReason}</Text>
                    {view.nextStep === "switch" && alternative && (
                        <Button size="small" onClick={() => onSwitch(alternative.value)}>
                            改用 {alternative.label}
                        </Button>
                    )}
                    {view.nextStep === "settings" && (
                        <Link to="/settings" style={{ fontSize: 12 }}>到設定頁下載</Link>
                    )}
                </Space>
            )}
            {view.warning && (
                <Text style={{ fontSize: 12, color: "#d4a72d" }}>{view.warning}</Text>
            )}
        </Space>
    )
}
