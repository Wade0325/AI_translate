import { describe, it, expect } from 'vitest';
import { formatTokensTick } from './formatters';
import { tokenAxisProps, tokenAxisTicks } from './tokenAxis';

// 把 formatTokensTick 的標籤換回數字：「400」→ 400、「3.5k」→ 3,500、「15k」→ 15,000、「1.5M」→ 1,500,000
function labelToTokens(label) {
  const match = /^(\d+)(?:\.(\d))?([kM]?)$/.exec(label);
  if (!match) throw new Error(`看不懂的標籤 ${label}`);
  const [, whole, tenth = '0', unit] = match;
  const unitSize = { '': 1, k: 1_000, M: 1_000_000 }[unit];
  return ((Number(whole) * 10 + Number(tenth)) * unitSize) / 10;
}

// 0 到 2,000 的每個整數；再往上每次乘 1.01 到 1 兆；加上換間距的邊界（5 格剛好裝滿 5 × 間距、多 1 就要換大一級）
const SWEEP_MAXIMA = (() => {
  const maxima = [];
  for (let max = 0; max <= 2_000; max++) maxima.push(max);
  for (let max = 2_000; max <= 1e12; max *= 1.01) maxima.push(Math.round(max));
  for (let magnitude = 1; magnitude <= 1e10; magnitude *= 10) {
    for (const step of [1, 2, 5].map((mantissa) => mantissa * magnitude)) {
      maxima.push(5 * step, 5 * step + 1);
    }
  }
  return maxima;
})();

describe('tokenAxisTicks：用量圖 Y 軸的 token 刻度', () => {
  it.each([
    [0, [0, 1, 2, 3]],
    [7, [0, 2, 4, 6, 8]],
    [950, [0, 200, 400, 600, 800, 1_000]],
    [10_500, [0, 5_000, 10_000, 15_000]],
    [13_500, [0, 5_000, 10_000, 15_000]],
    [1_050_000, [0, 500_000, 1_000_000, 1_500_000]],
    [2_600_000, [0, 1_000_000, 2_000_000, 3_000_000]],
    [2_600_000_000, [0, 1_000_000_000, 2_000_000_000, 3_000_000_000]],
  ])('最大值 %s 的刻度是 %j', (max, expected) => {
    expect(tokenAxisTicks(max)).toEqual(expected);
  });

  it.each([NaN, Infinity, -Infinity])('不是有限的數（%s）時和最大值 0 一樣，圖表照樣有刻度', (max) => {
    expect(tokenAxisTicks(max)).toEqual([0, 1, 2, 3]);
  });

  // Recharts 自己挑刻度時，這幾個最大值會挑出 10,500 → 11k、1,050,000 → 1.1M、1,950,000 → 2.0M（#160）
  it.each([13_500, 1_400_000, 2_600_000])('最大值 %s 的每個刻度，標籤換回數字就是刻度本身', (max) => {
    for (const tick of tokenAxisTicks(max)) {
      expect(labelToTokens(formatTokensTick(tick))).toBe(tick);
    }
  });

  it('從 0 到 1 兆的最大值，每個刻度的標籤都準', () => {
    for (const max of SWEEP_MAXIMA) {
      for (const tick of tokenAxisTicks(max)) {
        expect(labelToTokens(formatTokensTick(tick)), `最大值 ${max} 的刻度 ${tick}`).toBe(tick);
      }
    }
  });

  it('從 0 到 1 兆的最大值，刻度從 0 起、間距是 1、2、5 × 10ⁿ，4 到 6 個，最後一個剛好涵蓋最大值', () => {
    for (const max of SWEEP_MAXIMA) {
      const ticks = tokenAxisTicks(max);
      const step = ticks[1];
      const caseLabel = `最大值 ${max} 的刻度 ${JSON.stringify(ticks)}`;
      expect(String(step), caseLabel).toMatch(/^[125]0*$/);
      expect(ticks, caseLabel).toEqual(ticks.map((_, i) => i * step));
      expect(ticks.length, caseLabel).toBeGreaterThanOrEqual(4);
      expect(ticks.length, caseLabel).toBeLessThanOrEqual(6);
      expect(ticks.at(-1), caseLabel).toBeGreaterThanOrEqual(max);
      // 不多留一格空白；只有最大值小到湊不滿 4 個刻度時（0 到 2）例外
      if (max > 2) expect(ticks.at(-2), caseLabel).toBeLessThan(max);
    }
  });
});

describe('tokenAxisProps：用量圖 token Y 軸給 Recharts YAxis 的 props', () => {
  it('刻度依資料列裡最大的 tokens 產生，範圍到最後一個刻度，標籤用 formatTokensTick', () => {
    const rows = [{ day: '1', tokens: 4_200 }, { day: '2', tokens: 13_500 }, { day: '3', tokens: 0 }];
    expect(tokenAxisProps(rows)).toEqual({
      ticks: [0, 5_000, 10_000, 15_000],
      domain: [0, 15_000],
      tickFormatter: formatTokensTick,
    });
  });

  it('沒有資料列時刻度是 0 到 3', () => {
    expect(tokenAxisProps([])).toEqual({
      ticks: [0, 1, 2, 3],
      domain: [0, 3],
      tickFormatter: formatTokensTick,
    });
  });
});
