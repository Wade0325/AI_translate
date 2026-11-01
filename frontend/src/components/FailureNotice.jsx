import { Tooltip, Typography } from "antd"
import { Link } from "react-router-dom"
import { describeFailure } from "@/utils/failure"

const { Text, Paragraph } = Typography

/** 錯誤碼與細節寫成一行，使用者回報問題時整行複製。 */
function codeLine({ code, detail }) {
    return [code && `錯誤碼 ${code}`, detail].filter(Boolean).join(" · ")
}

/**
 * 任務失敗的完整說明（轉錄頁的檔案卡用）：原因、下一步、前往處理的連結，最下面是錯誤碼與細節，
 * 可以一鍵複製去回報。failure 是 { code, detail }（utils/failure.js 的 failureOf）。
 */
export function FailureNotice({ failure }) {
    const shown = describeFailure(failure)
    const line = codeLine(shown)
    return (
        <div
            data-testid="failure-notice"
            style={{
                borderTop: "1px solid rgba(224, 82, 82, 0.2)",
                background: "rgba(224, 82, 82, 0.06)",
                padding: "8px 12px 10px 56px",
                display: "flex",
                flexDirection: "column",
                gap: 4,
            }}
        >
            <Text style={{ fontSize: 12, fontWeight: 500, color: "#f08a8a" }}>{shown.reason}</Text>
            {(shown.nextStep || shown.action) && (
                <Text style={{ fontSize: 12, color: "#c8c8d8" }}>
                    {shown.nextStep}
                    {shown.action && (
                        <Link to={shown.action.to} style={{ marginLeft: 8 }}>{shown.action.label}</Link>
                    )}
                </Text>
            )}
            {line && (
                <Paragraph
                    copyable={{ text: line, tooltips: ["複製錯誤碼與細節", "已複製"] }}
                    ellipsis={{ rows: 2, expandable: true, symbol: "展開" }}
                    style={{ fontSize: 11, color: "#8888a8", margin: 0 }}
                >
                    {line}
                </Paragraph>
            )}
        </div>
    )
}

/**
 * 一行的失敗原因（Tasks、History 用）：原因寫出來，滑過去看下一步、錯誤碼與細節。
 */
export function FailureSummary({ failure, style }) {
    const shown = describeFailure(failure)
    const line = codeLine(shown)
    const tip = (shown.nextStep || line) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {shown.nextStep && <span>{shown.nextStep}</span>}
            {line && <span style={{ opacity: 0.75 }}>{line}</span>}
        </div>
    )
    return (
        <Tooltip title={tip}>
            <Text ellipsis style={{ fontSize: 11, color: "#e05252", ...style }}>
                {shown.reason}
            </Text>
        </Tooltip>
    )
}
