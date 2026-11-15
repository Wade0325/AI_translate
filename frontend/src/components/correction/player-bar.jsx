import { Button, Select, Slider } from "antd"
import { Pause, Play } from "lucide-react"
import { formatClock } from "@/utils/formatters"
import { PLAYBACK_RATES } from "@/utils/correction"

const BAR_STYLE = {
    display: "flex",
    alignItems: "center",
    gap: 16,
    padding: "10px 16px",
    borderBottom: "1px solid #3a3a5c",
    background: "#1e1e3a",
    flexShrink: 0,
}

const RATE_OPTIONS = PLAYBACK_RATES.map((rate) => ({ value: rate, label: `${rate} 倍` }))

/**
 * 校正頁上方固定的播放列（#347）：播放與暫停、進度條、目前時間與總長、播放速度。保留音檔不能播放時
 * 整列換成 notice 那一句。
 *
 * @param {{
 *   playing: boolean,
 *   time: number,
 *   total: number,
 *   rate: number,
 *   notice: string | null,
 *   onToggle: () => void,
 *   onSeek: (seconds: number) => void,
 *   onRate: (rate: number) => void,
 * }} props
 */
export function PlayerBar({ playing, time, total, rate, notice, onToggle, onSeek, onRate }) {
    if (notice) {
        return (
            <div role="status" style={{ ...BAR_STYLE, color: "#d4a72d", fontSize: 13, minHeight: 53 }}>
                {notice}
            </div>
        )
    }

    const max = total > 0 ? total : 0
    return (
        <div role="group" aria-label="播放列" style={BAR_STYLE}>
            <Button
                type="primary"
                shape="circle"
                aria-label={playing ? "暫停" : "播放"}
                icon={playing ? <Pause size={16} /> : <Play size={16} />}
                onClick={onToggle}
            />
            <span
                aria-label="目前時間與總長"
                className="correction-clock"
                style={{ color: "#e8e8e8", fontSize: 13, whiteSpace: "nowrap" }}
            >
                {formatClock(time)} / {formatClock(max)}
            </span>
            <Slider
                style={{ flex: 1, margin: "0 4px" }}
                min={0}
                max={max || 1}
                step={0.1}
                value={Math.min(time, max)}
                disabled={!max}
                tooltip={{ formatter: (value) => formatClock(value) }}
                ariaLabelForHandle="播放進度"
                onChange={(value) => onSeek(value)}
            />
            <Select
                aria-label="播放速度"
                value={rate}
                options={RATE_OPTIONS}
                onChange={onRate}
                style={{ width: 96 }}
            />
        </div>
    )
}
