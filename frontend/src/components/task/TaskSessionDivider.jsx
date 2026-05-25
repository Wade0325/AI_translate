import { Typography } from "antd"
import { formatDateTime } from "@/utils/formatters"

const { Text } = Typography

export default function TaskSessionDivider({ startedAt, fileCount, showTopMargin = true }) {
  const label = startedAt
    ? `${formatDateTime(startedAt)} · ${fileCount} 個檔案`
    : `${fileCount} 個檔案`

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        margin: showTopMargin ? "20px 0 12px" : "0 0 12px",
      }}
    >
      <div style={{ flex: 1, height: 1, background: "#3a3a5c" }} />
      <Text style={{ fontSize: 11, color: "#8888a8", whiteSpace: "nowrap" }}>
        {label}
      </Text>
      <div style={{ flex: 1, height: 1, background: "#3a3a5c" }} />
    </div>
  )
}
