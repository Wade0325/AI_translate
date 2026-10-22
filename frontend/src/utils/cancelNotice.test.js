import { describe, expect, it } from 'vitest';
import { cancelNotice } from './cancelNotice.js';

describe('按取消之後顯示的訊息', () => {
  it('取消了：說取消了哪個檔案的任務', () => {
    expect(cancelNotice({ file_uid: 'f1', cancelled: true }, 'a.wav'))
      .toEqual({ type: 'info', content: '已取消任務：a.wav' });
  });

  it('任務已經結束（完成或失敗，或正在收尾）：說來不及取消，不叫使用者再等', () => {
    expect(cancelNotice({ file_uid: 'f1', cancelled: false, reason: 'finished' }, 'a.wav'))
      .toEqual({ type: 'info', content: '任務已經結束，無法取消。' });
  });

  it('任務還沒提交到佇列（可能還在上傳）：請使用者稍後再按一次', () => {
    expect(cancelNotice({ file_uid: 'f1', cancelled: false, reason: 'not-started' }, 'a.wav'))
      .toEqual({ type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' });
  });

  it('沒有取消、原因又認不得（沒帶，或後端多了新的原因）：不猜是哪一種', () => {
    for (const response of [{ file_uid: 'f1', cancelled: false }, { file_uid: 'f1', cancelled: false, reason: 'busy' }]) {
      expect(cancelNotice(response, 'a.wav')).toEqual({ type: 'warning', content: '任務沒有取消，請稍後再試。' });
    }
  });
});
