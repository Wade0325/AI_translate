/** Dashboard / Billing 用量圖共用的 Tooltip：Tokens · Files 與 Cost 兩行。 */
export function UsageTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <RechartsTooltipBox label={label}>
      <div style={{ fontSize: 12, color: '#8888a8' }}>
        Tokens: {row.tokens.toLocaleString()} · Files: {row.files}
      </div>
      <div style={{ fontSize: 12, color: '#2dd4a8' }}>
        Cost: ${row.cost.toFixed(4)}
      </div>
    </RechartsTooltipBox>
  );
}

/** 深色佈景下共用的 Recharts Tooltip 容器；各圖表自行提供內容，外觀統一於此。 */
export default function RechartsTooltipBox({ label, children, style }) {
  return (
    <div
      style={{
        borderRadius: 8,
        border: '1px solid #3a3a5c',
        background: '#1e1e3a',
        padding: 12,
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        ...(style || {}),
      }}
    >
      {label != null && (
        <div style={{ fontSize: 13, fontWeight: 500, color: '#e8e8e8' }}>
          {label}
        </div>
      )}
      {children}
    </div>
  );
}
