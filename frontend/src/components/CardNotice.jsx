/**
 * 檔案卡底部的一列提醒（轉錄頁與結果頁的檔案卡用）：任務是完成的，所以用提醒的顏色，不用失敗的紅色。
 * paddingLeft 讓文字和卡片上的檔名對齊；style 補上內容的排列方式。
 * @param {{ testId: string, paddingLeft?: number, style?: import('react').CSSProperties, children: import('react').ReactNode }} props
 */
export function CardNotice({ testId, paddingLeft = 56, style, children }) {
    return (
        <div
            data-testid={testId}
            style={{
                borderTop: "1px solid rgba(212, 167, 45, 0.2)",
                background: "rgba(212, 167, 45, 0.06)",
                padding: `8px 12px 10px ${paddingLeft}px`,
                ...style,
            }}
        >
            {children}
        </div>
    )
}
