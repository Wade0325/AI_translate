import { describe, it, expect } from 'vitest';
import {
  formatDateTime,
  formatDuration,
  formatElapsed,
  formatTokensTick,
  localDateKey,
} from './formatters';

// 日期與時間的結果依時區而定：vite.config.js 把測試固定在台北時間，本機與 CI（UTC）結果一樣

describe('formatElapsed：經過的秒數顯示成多久以前', () => {
  it.each([
    [59, '剛剛'],
    [60, '1 分鐘前'],
    [3599, '59 分鐘前'],
    [3600, '1 小時前'],
    [86399, '23 小時前'],
    [86400, '1 天前'],
  ])('%s 秒顯示成「%s」', (seconds, expected) => {
    expect(formatElapsed(seconds)).toBe(expected);
  });

  it.each([0, null, undefined, -30])('沒有經過時間（%s）時不顯示', (seconds) => {
    expect(formatElapsed(seconds)).toBe('');
  });
});

describe('formatDuration：音檔長度顯示成時:分:秒', () => {
  it.each([
    [5, '0:05'],
    [59.9, '0:59'],
    [61, '1:01'],
    [3599, '59:59'],
    [3600, '1:00:00'],
    [3661, '1:01:01'],
  ])('%s 秒顯示成 %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });

  it.each([0, null, undefined, NaN])('沒有長度（%s）時顯示 0:00', (seconds) => {
    expect(formatDuration(seconds)).toBe('0:00');
  });
});

describe('formatDateTime：任務的時間顯示成月/日與 12 小時制的時:分', () => {
  // 日期和時間之間的空白由 Node 內建的 ICU 決定（目前是 U+2009 窄空白），用 \s 比對
  it('帶時區的時間換成台北時間顯示', () => {
    expect(formatDateTime('2026-01-04T16:30:00Z')).toMatch(/^01\/05\s上午12:30$/);
  });

  it('後端寫的本地時間（沒有時區、帶微秒）照原本的時刻顯示', () => {
    expect(formatDateTime('2026-10-20T13:05:00.123456')).toMatch(/^10\/20\s下午01:05$/);
  });

  it.each(['', null, undefined])('沒有時間（%j）時顯示空字串', (value) => {
    expect(formatDateTime(value)).toBe('');
  });

  it.each(['not a date', '2026-13-45T00:00:00'])('無法解析的字串（%j）原樣顯示', (value) => {
    expect(formatDateTime(value)).toBe(value);
  });
});

describe('localDateKey：對齊後端每日用量的本地日期', () => {
  it('用台北的日期，不是 UTC 的日期', () => {
    // 台北的 2026-01-01 00:00，UTC 還是 2025-12-31
    expect(localDateKey(new Date('2025-12-31T16:00:00Z'))).toBe('2026-01-01');
  });

  it('月與日補成兩位數', () => {
    expect(localDateKey(new Date(2026, 2, 7, 12))).toBe('2026-03-07');
  });

  it('兩位數的月與日照原樣', () => {
    expect(localDateKey(new Date(2026, 9, 20, 23, 59))).toBe('2026-10-20');
  });

  it('無效的日期沒有日期鍵，不會變成 NaN-NaN-NaN', () => {
    expect(localDateKey(new Date('not a date'))).toBeNull();
  });
});

describe('formatTokensTick：用量圖 Y 軸的 token 數刻度', () => {
  it.each([
    [0, '0'],
    [400, '400'],
    [999, '999'],
    [1_000, '1.0k'],
    [3_500, '3.5k'],
    [10_000, '10k'],
    [12_400, '12k'],
    [1_000_000, '1.0M'],
    [1_200_000, '1.2M'],
  ])('%s 顯示成 %s', (tokens, expected) => {
    expect(formatTokensTick(tokens)).toBe(expected);
  });

  it.each([
    [9_949, '9.9k'],
    [9_950, '10k'],
    [9_999, '10k'],
    [10_001, '10k'],
    [999_499, '999k'],
    [999_500, '1.0M'],
    [999_999, '1.0M'],
    [1_000_001, '1.0M'],
  ])('進到下一個單位的邊界：%s 顯示成 %s', (tokens, expected) => {
    expect(formatTokensTick(tokens)).toBe(expected);
  });

  // 1.95 這類剛好一半的值，toFixed 會受浮點誤差影響變成 1.9
  it.each([
    [1_950, '2.0k'],
    [1_950_000, '2.0M'],
  ])('剛好一半時照四捨五入進位：%s 顯示成 %s', (tokens, expected) => {
    expect(formatTokensTick(tokens)).toBe(expected);
  });
});
