import { describe, it, expect } from 'vitest';
import { bulkUndoMessage, formatRecordTime, historyEntries, valueLabel } from './correctionHistory';

/** GET /transcripts/{task_uuid} 的一個片段；沒寫的欄位是沒有校正過的樣子。 */
const segment = (fields = {}) => ({
  seg_key: '0.0001', start: 4, text: '今天先看進度', original_text: '今天先看進度', speaker: 'S0',
  original_speaker: 'S0', corrected: false, deleted: false, deleted_text: null, has_correction_records: false,
  ...fields,
});

let nextId = 0;
/** 一筆校正紀錄（後端的 CorrectionRecordResponse）；沒寫的是一個片段、一筆的操作。 */
const record = (field, before, after, fields = {}) => {
  nextId += 1;
  return {
    id: nextId, field, old_value: before, new_value: after, operation_id: `op-${nextId}`,
    created_at: '2026-11-15T21:03:05', operation_record_count: 1, operation_segment_count: 1, ...fields,
  };
};

const history = (records) => ({
  seg_key: '0.0001', original_text: '今天先看進度', original_speaker: 'S0', records,
});

describe('historyEntries：片段的歷程（#355）', () => {
  it('最上面是最新的一筆，最下面是原始轉錄；後端給的是舊的在前', () => {
    const records = [
      record('text', '今天先看進度', '第一版'),
      record('text', '第一版', '第二版'),
      record('text', '第二版', '第三版'),
    ];
    const entries = historyEntries(history(records), segment({ text: '第三版', corrected: true }));

    expect(entries.map((e) => (e.kind === 'original' ? 'original' : e.after))).toEqual(
      ['第三版', '第二版', '第一版', 'original']);
    expect(entries.at(-1)).toMatchObject({ kind: 'original', text: '今天先看進度', speaker: 'S0' });
  });

  it('回到某一筆：只把那一筆改的那一項改回它當時的改後', () => {
    const records = [
      record('text', '今天先看進度', '第一版'),
      record('speaker', 'S0', 'S1'),
      record('text', '第一版', '第二版'),
    ];
    const [second, speaker, first] = historyEntries(
      history(records), segment({ text: '第二版', speaker: 'S1', corrected: true }));

    expect(first.request).toEqual({ text: '第一版' });
    expect(speaker.request).toBeNull();
    expect(second.request).toBeNull();
  });

  it('文字與說話者各自最新的一筆是現在的內容：標成現在、沒有要送的', () => {
    const records = [record('text', '今天先看進度', '第一版'), record('speaker', 'S0', 'S1')];
    const entries = historyEntries(history(records), segment({ text: '第一版', speaker: 'S1', corrected: true }));

    expect(entries.map((e) => e.current)).toEqual([true, true, false]);
    expect(entries.map((e) => e.request)).toEqual([null, null, { text: '今天先看進度', speaker: 'S0' }]);
  });

  it('回到原始轉錄：文字與說話者有變的都回去，在同一個請求裡（後端各記一筆、共用一個操作編號）', () => {
    const records = [record('text', '今天先看進度', '改過'), record('speaker', 'S0', 'S2')];
    const original = historyEntries(history(records), segment({ text: '改過', speaker: 'S2', corrected: true })).at(-1);

    expect(original.request).toEqual({ text: '今天先看進度', speaker: 'S0' });
    expect(original.current).toBe(false);
  });

  it('回到原始轉錄之後，原始轉錄和現在相同、沒有要送的，之前的每一筆都還能回去', () => {
    const records = [
      record('text', '今天先看進度', '第一版'),
      record('text', '第一版', '第二版'),
      record('text', '第二版', '今天先看進度'),
    ];
    const entries = historyEntries(history(records), segment({ has_correction_records: true }));

    // 「現在」只標在最新的那一筆，原始轉錄只是和現在相同
    expect(entries.map((e) => e.current)).toEqual([true, false, false, false]);
    expect(entries.map((e) => e.request)).toEqual([null, { text: '第二版' }, { text: '第一版' }, null]);
  });

  it('和現在相同但不是最新的那一版：不標現在，也沒有要送的', () => {
    const records = [
      record('text', '今天先看進度', '第一版'),
      record('text', '第一版', '第二版'),
      record('text', '第二版', '第一版'),
    ];
    const entries = historyEntries(history(records), segment({ text: '第一版', corrected: true }));

    expect(entries.map((e) => [e.current, e.request])).toEqual([
      [true, null], [false, { text: '第二版' }], [false, null], [false, { text: '今天先看進度' }]]);
  });

  it('刪掉片段是文字改成空的：回到那一筆就是刪掉；說話者的「沒有」是 null', () => {
    const records = [record('text', '今天先看進度', ''), record('speaker', 'S0', null)];
    const entries = historyEntries(history(records), segment({ text: '今天先看進度', speaker: 'S0' }));

    expect(entries[0].request).toEqual({ speaker: null });
    expect(entries[1].request).toEqual({ text: '' });
  });

  it('改到超過一個片段的操作是整批操作，帶著它一共改了幾個片段與操作編號', () => {
    const records = [
      record('text', '今天先看進度', '今天先看進展', { operation_id: 'replace-all', operation_record_count: 5, operation_segment_count: 5 }),
      record('text', '今天先看進展', '今天先看進度', { operation_id: 'revert', operation_record_count: 2, operation_segment_count: 1 }),
    ];
    const [revert, replaceAll] = historyEntries(history(records), segment({ has_correction_records: true }));

    expect(replaceAll).toMatchObject({ bulk: true, segmentCount: 5, operationId: 'replace-all' });
    // 一個片段的文字與說話者一起改（例如回到原始轉錄）是兩筆、一個片段，不是整批操作
    expect(revert).toMatchObject({ bulk: false, segmentCount: 1 });
  });

  it('還沒有校正紀錄時只有原始轉錄', () => {
    expect(historyEntries(history([]), segment())).toEqual([
      { kind: 'original', key: 'original', text: '今天先看進度', speaker: 'S0', current: true, request: null },
    ]);
  });
});

describe('valueLabel：歷程裡的改前與改後', () => {
  it('文字照寫；空的文字是刪掉這個片段', () => {
    expect(valueLabel('text', '今天')).toBe('今天');
    expect(valueLabel('text', '')).toBe('（刪掉這個片段）');
    expect(valueLabel('text', null)).toBe('（刪掉這個片段）');
  });

  it('說話者照寫；沒有說話者另外寫', () => {
    expect(valueLabel('speaker', 'S1')).toBe('S1');
    expect(valueLabel('speaker', null)).toBe('（沒有說話者）');
  });
});

// 日期與時間的結果依時區而定：vite.config.js 把測試固定在台北時間
describe('formatRecordTime：什麼時候改的', () => {
  it('後端寫的本地時間（沒有時區）顯示成月/日與 12 小時制的時:分:秒', () => {
    expect(formatRecordTime('2026-11-15T21:03:05')).toMatch(/^11\/15\s下午09:03:05$/);
  });

  it.each(['', null, 'not a date'])('沒有或讀不懂的時間（%j）不顯示', (value) => {
    expect(formatRecordTime(value)).toBe('');
  });
});

describe('bulkUndoMessage：按了「整批復原」之後寫的結果', () => {
  it('全部還原', () => {
    expect(bulkUndoMessage({ restored: 5, skipped: 0 })).toEqual({ type: 'success', content: '已整批復原 5 個片段' });
  });

  it('之後又改過的片段略過，寫出略過了幾個', () => {
    expect(bulkUndoMessage({ restored: 4, skipped: 1 })).toEqual({
      type: 'warning', content: '已整批復原 4 個片段；略過 1 個在這之後又改過的片段',
    });
  });

  it('全部都在之後又改過時一個都沒有還原', () => {
    expect(bulkUndoMessage({ restored: 0, skipped: 5 })).toEqual({
      type: 'warning', content: '沒有復原：這 5 個片段在這之後都又改過',
    });
  });
});
