import { describe, it, expect } from 'vitest';
import { ApiError } from '../services/api';
import { CORRECTION_PATH, PLAYBACK_RATES, correctionPath, unavailableMessage } from './correction';

describe('correctionPath：校正頁的網址帶任務 id', () => {
  it('重新整理或之後再開都是同一個網址', () => {
    expect(correctionPath('3f2a')).toBe('/correction/3f2a');
    expect(CORRECTION_PATH).toBe('/correction/:taskUuid');
  });
});

describe('unavailableMessage：直接開不能校正的任務的網址時，畫面寫的那一句', () => {
  it.each([
    ['not_completed', '這個任務還沒完成，完成之後才能校正。'],
    ['no_segments', '這個任務沒有可以逐段校正的片段：轉錄結果是空的，或是較早版本轉錄、只存了整份轉錄結果的任務。'],
    ['with_translation', '這個任務是轉錄並翻譯，翻譯過的結果不能校正。'],
  ])('後端說 %s 時', (reason, message) => {
    expect(unavailableMessage({ reason })).toBe(message);
  });

  it.each([404, 400])('任務不存在（後端回 %s）時', (status) => {
    expect(unavailableMessage({ error: new ApiError(status, '找不到此任務紀錄') }))
      .toBe('找不到這個任務，可能已經在 History 刪掉了。');
  });

  it('讀不到（例如 app 沒在執行）時請使用者重新整理', () => {
    expect(unavailableMessage({ error: new TypeError('Failed to fetch') }))
      .toBe('讀不到這個任務，請確認 Mimiji 還在執行，再重新整理一次。');
    expect(unavailableMessage({ error: new ApiError(500, 'boom') }))
      .toBe('讀不到這個任務，請確認 Mimiji 還在執行，再重新整理一次。');
  });

  it('後端多了不認得的原因時也有一句，不出錯', () => {
    expect(unavailableMessage({ reason: 'something_new' })).toBe('這個任務不能校正。');
  });
});

describe('PLAYBACK_RATES：播放速度的選項', () => {
  it('0.75 到 2 倍，預設的 1 倍在裡面', () => {
    expect(PLAYBACK_RATES).toEqual([0.75, 1, 1.25, 1.5, 2]);
  });
});
