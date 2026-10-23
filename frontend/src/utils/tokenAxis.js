/**
 * 用量圖的 token Y 軸：刻度 0、s、2s、…，標籤用 formatters.js 的 formatTokensTick 顯示。
 * 純函式，不 import React 與 Recharts；圖表用 tokenAxisProps 一次拿到刻度、範圍與標籤格式。
 *
 * 間距 s 只用 1、2、5 × 10ⁿ，選切出來不超過 5 格的最小間距，所以一定是 3 到 5 格（4 到 6 個
 * 刻度），最後一個刻度是不小於最大值的最小 s 倍數。token 是整數，間距至少 1；最大值小到
 * 切不滿 3 格（0 到 2）時補滿 3 格。
 *
 * 不讓 Recharts 自己挑刻度：它的間距可能是 3,500、350,000 這種數，刻度落在 10,500、1,050,000
 * 時，formatTokensTick 只顯示得出 11k、1.1M（#160）。間距是 1、2、5 × 10ⁿ 又最多 5 格時，
 * 1k 以上的刻度都是 100 的倍數、10k 以上都是 1,000 的倍數、1M 以上都是 100,000 的倍數，
 * 剛好是 formatTokensTick 顯示得出的位數，標籤一定準。刻度和標籤格式要成對才準，所以由
 * tokenAxisProps 一起給。
 */
import { formatTokensTick } from './formatters';

const MAX_INTERVALS = 5;
const MIN_INTERVALS = 3;
const NICE_MANTISSAS = [1, 2, 5];

/** 切出來不超過 MAX_INTERVALS 格的最小間距：1、2、5、10、20、50、…。 */
function smallestNiceStep(max) {
  for (let magnitude = 1; ; magnitude *= 10) {
    for (const mantissa of NICE_MANTISSAS) {
      const step = mantissa * magnitude;
      if (Math.ceil(max / step) <= MAX_INTERVALS) return step;
    }
  }
}

/**
 * 最大的 token 數 → Y 軸的刻度，例如 13,500 → [0, 5000, 10000, 15000]。
 * 不是有限的數時當成 0：NaN 會讓找間距的迴圈停不下來。
 */
export function tokenAxisTicks(maxTokens) {
  const max = Number.isFinite(maxTokens) ? maxTokens : 0;
  const step = smallestNiceStep(max);
  const intervals = Math.max(MIN_INTERVALS, Math.ceil(max / step));
  return Array.from({ length: intervals + 1 }, (_, i) => i * step);
}

/**
 * 圖表的資料列（每列有 tokens）→ Recharts YAxis 的 props：刻度、範圍（0 到最後一個刻度）與標籤格式。
 * 沒有資料列時刻度是 0 到 3。
 *
 *   <YAxis stroke="#8888a8" fontSize={12} {...tokenAxisProps(rows)} />
 */
export function tokenAxisProps(rows) {
  const ticks = tokenAxisTicks(Math.max(0, ...rows.map((row) => row.tokens)));
  return { ticks, domain: [0, ticks.at(-1)], tickFormatter: formatTokensTick };
}
