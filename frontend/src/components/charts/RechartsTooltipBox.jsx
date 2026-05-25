import React from 'react';

/**
 * Recharts 在深色佈景下使用的 Tooltip 容器。
 *
 * 各圖表自定義要顯示的內容（payload 解讀方式不同），但外觀統一在此控制。
 * 使用方式：
 *   function CustomTooltip({ active, payload, label }) {
 *     if (!active || !payload?.length) return null;
 *     return (
 *       <RechartsTooltipBox label={label}>
 *         {payload.map((p, i) => <div key={i}>...</div>)}
 *       </RechartsTooltipBox>
 *     );
 *   }
 *   <Tooltip content={<CustomTooltip />} />
 */
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
