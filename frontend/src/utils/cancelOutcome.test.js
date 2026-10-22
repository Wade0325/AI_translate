import { describe, expect, it } from 'vitest';
import { cancelOutcome } from './cancelOutcome.js';

// 取消端點沒有取消時的回應：只留測試用得到的欄位
const notCancelled = (reason) => ({ cancelled: false, reason });

describe('按取消之後', () => {
  it('取消了：說取消了哪個檔案的任務', () => {
    expect(cancelOutcome({ cancelled: true }, 'a.wav')).toEqual({
      cancelled: true,
      notice: { type: 'info', content: '已取消任務：a.wav' },
    });
  });

  it('任務已經結束（完成或失敗，或正在收尾）：說來不及取消，不叫使用者再等', () => {
    expect(cancelOutcome(notCancelled('finished'), 'a.wav')).toEqual({
      cancelled: false,
      notice: { type: 'info', content: '任務已經結束，無法取消。' },
    });
  });

  it('任務還沒提交到佇列（可能還在上傳）：請使用者稍後再按一次', () => {
    expect(cancelOutcome(notCancelled('not-started'), 'a.wav')).toEqual({
      cancelled: false,
      notice: { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' },
    });
  });

  it('沒有取消、原因又認不得（沒帶、後端多了新的原因，或回應沒有內容）：只說沒有取消，不猜原因', () => {
    for (const response of [notCancelled(undefined), notCancelled('busy'), null]) {
      expect(cancelOutcome(response, 'a.wav')).toEqual({
        cancelled: false,
        notice: { type: 'warning', content: '任務沒有取消。' },
      });
    }
  });
});
