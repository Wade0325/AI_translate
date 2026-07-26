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
