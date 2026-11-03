import { describe, expect, it } from 'vitest';
import { TASK_STATUS } from '../constants/taskStatus';
import { applyFileResult } from './fileResult.js';
import { describeTailLoss } from './tailLoss.js';

describe('轉錄結果可能掉尾：寫出從哪裡起可能沒有轉錄到（#257）', () => {
  it.each([
    [45.9, '從 00:45 起可能沒有轉錄到'],
    [3000.4, '從 50:00 起可能沒有轉錄到'],
    [6612, '從 1:50:12 起可能沒有轉錄到'],
    // 一句都沒轉出來就停了的段：從那一段的開頭算
    [0, '從 00:00 起可能沒有轉錄到'],
  ])('起點是 %s 秒：「%s」', (seconds, reason) => {
    expect(describeTailLoss(seconds).reason).toBe(reason);
  });

  it('下一步：去聽那一段，只是音樂或環境音就不必理會，有說話就剪出來再轉錄', () => {
    const { nextStep } = describeTailLoss(3000.4);
    expect(nextStep).toContain('音樂或環境音');
    expect(nextStep).toContain('剪成另一個檔案再轉錄');
  });

  it.each([null, undefined])('沒有掉尾（%s）時不顯示', (seconds) => {
    expect(describeTailLoss(seconds)).toBeNull();
  });
});

describe('完成的檔案卡記下可能掉尾的起點', () => {
  const file = { uid: 'f1', name: 'meeting.wav', status: 'processing' };
  const completed = (result) => ({
    task_uuid: 'task-1', status_code: TASK_STATUS.COMPLETED, status_text: '任務完成', result,
  });

  it('完成的結果帶著起點時記下來', () => {
    const next = applyFileResult(file, completed({ transcripts: {}, tail_loss_from_seconds: 3000.4 }));
    expect(next.tailLossFrom).toBe(3000.4);
  });

  it('沒有掉尾時是 null', () => {
    expect(applyFileResult(file, completed({ transcripts: {}, tail_loss_from_seconds: null })).tailLossFrom)
      .toBeNull();
    expect(applyFileResult(file, completed({ transcripts: {} })).tailLossFrom).toBeNull();
  });
});
