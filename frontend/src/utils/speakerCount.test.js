import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SPEAKER_COUNT,
  formatSpeakerCount,
  isSpeakerCount,
  speakerCountMismatch,
  speakerCountOptions,
} from './speakerCount.js';

describe('說話者人數的選單（#351 第 1 點）', () => {
  it('選項是 Auto 與 1 到 8，預設 Auto', () => {
    expect(speakerCountOptions.map((o) => o.value)).toEqual(['auto', 1, 2, 3, 4, 5, 6, 7, 8]);
    expect(speakerCountOptions.map((o) => o.label)).toEqual(['Auto', '1', '2', '3', '4', '5', '6', '7', '8']);
    expect(DEFAULT_SPEAKER_COUNT).toBe('auto');
  });

  it('只認得 Auto 與 1 到 8 的整數：字串的數字、0、9 與開關的值都不算', () => {
    expect(['auto', 1, 5, 8].map(isSpeakerCount)).toEqual([true, true, true, true]);
    expect(['Auto', '2', 0, 9, 2.5, true, false, null, undefined].map(isSpeakerCount))
      .toEqual([false, false, false, false, false, false, false, false, false]);
  });

  it('檔案卡的標籤寫出所選的人數', () => {
    expect(['auto', 1, 3].map(formatSpeakerCount)).toEqual(['Speakers: Auto', 'Speakers: 1', 'Speakers: 3']);
  });
});

describe('結果的說話者人數和所選的不同時的提醒（#351 第 4 點）', () => {
  it('選了 2 到 8 人、結果不同時提醒，多了少了都算', () => {
    expect(speakerCountMismatch(2, 3)).toBe('選了 2 人，結果有 3 位說話者');
    expect(speakerCountMismatch(4, 1)).toBe('選了 4 人，結果有 1 位說話者');
  });

  it('人數相同、照模型判斷、選 1 人或舊任務（沒有記錄所選的人數）都不提醒', () => {
    expect(speakerCountMismatch(3, 3)).toBeNull();
    expect(speakerCountMismatch('auto', 3)).toBeNull();
    expect(speakerCountMismatch(1, 1)).toBeNull();
    expect(speakerCountMismatch(null, 2)).toBeNull();
    expect(speakerCountMismatch(undefined, 2)).toBeNull();
  });

  it('不知道結果有幾位、或結果沒有任何一行（0 位，結果頁也不顯示人數）時不提醒', () => {
    expect(speakerCountMismatch(2, undefined)).toBeNull();
    expect(speakerCountMismatch(2, null)).toBeNull();
    expect(speakerCountMismatch(2, 0)).toBeNull();
  });
});
