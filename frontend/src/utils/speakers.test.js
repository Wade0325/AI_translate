import { describe, it, expect } from 'vitest';
import {
  nextSpeakerAfter,
  reassignMessage,
  shownSpeaker,
  showsAsCorrected,
  speakerChoices,
  speakerCounts,
} from './speakers';

/** 片段裡用得到的欄位：校正後與原始轉錄的文字與說話者。 */
const seg = (speaker, { originalSpeaker = speaker, text = 'A', originalText = text } = {}) => ({
  seg_key: Math.random().toString(36), start: 0, speaker, original_speaker: originalSpeaker, text, original_text: originalText,
  corrected: speaker !== originalSpeaker || text !== originalText, deleted: false, has_correction_records: false,
});

describe('speakerCounts：每位說話者有幾個片段（#354）', () => {
  it('照號碼排序（S2 在 S10 前面），沒有說話者的片段排在最後', () => {
    const segments = [seg('S10'), seg('S2'), seg(null), seg('S0'), seg('S2'), seg(undefined)];
    expect(speakerCounts(segments)).toEqual([['S0', 1], ['S2', 2], ['S10', 1], [null, 2]]);
  });

  it('看校正後的說話者，不看原始轉錄', () => {
    expect(speakerCounts([seg('S0', { originalSpeaker: 'S3' })])).toEqual([['S0', 1]]);
  });

  it('沒有片段時是空的', () => {
    expect(speakerCounts([])).toEqual([]);
  });
});

describe('speakerChoices：選單上可以換成的說話者', () => {
  it('現有的其他說話者，加上新的說話者', () => {
    expect(speakerChoices(['S0', 'S1', 'S2'], 'S1', 'S3')).toEqual([
      { speaker: 'S0', isNew: false }, { speaker: 'S2', isNew: false }, { speaker: 'S3', isNew: true },
    ]);
  });

  it('沒有說話者的片段：現有的每一位都可以選', () => {
    expect(speakerChoices(['S0'], null, 'S1')).toEqual([{ speaker: 'S0', isNew: false }, { speaker: 'S1', isNew: true }]);
  });
});

describe('nextSpeakerAfter：新的說話者編號（#354 第 1 點）', () => {
  it('取後端給的編號與片段裡的說話者之後，較大的那個', () => {
    expect(nextSpeakerAfter('S2', [seg('S0'), seg('S1')])).toBe('S2');
    expect(nextSpeakerAfter('S2', [seg('S0'), seg('S2')])).toBe('S3');
    expect(nextSpeakerAfter('S2', [seg('S10')])).toBe('S11');
  });

  it('只會變大：指定了新的說話者又復原，那個編號也不再給（後端也照這樣算）', () => {
    expect(nextSpeakerAfter('S3', [seg('S0')])).toBe('S3');
  });

  it('沒有任何說話者時從 S0 起', () => {
    expect(nextSpeakerAfter('S0', [seg(null)])).toBe('S0');
  });
});

describe('shownSpeaker：片段那一列寫的說話者', () => {
  it('存檔中與失敗時寫送出的說話者，其他時候寫片段現在的說話者', () => {
    const segment = seg('S0');
    expect(shownSpeaker(segment, undefined)).toBe('S0');
    expect(shownSpeaker(segment, { status: 'saving', request: { speaker: 'S1' } })).toBe('S1');
    expect(shownSpeaker(segment, { status: 'failed', request: { speaker: 'S2' }, message: 'x' })).toBe('S2');
    expect(shownSpeaker(segment, { status: 'saved' })).toBe('S0');
  });

  it('送出的只有文字時照片段現在的說話者', () => {
    expect(shownSpeaker(seg('S0'), { status: 'saving', request: { text: 'B' } })).toBe('S0');
  });
});

describe('showsAsCorrected：要不要標「校正過」', () => {
  it('照模型分出的說話者顯示時，文字或說話者改過都算', () => {
    expect(showsAsCorrected(seg('S1', { originalSpeaker: 'S0' }), false)).toBe(true);
    expect(showsAsCorrected(seg('S0', { text: 'B', originalText: 'A' }), false)).toBe(true);
    expect(showsAsCorrected(seg('S0'), false)).toBe(false);
  });

  it('整份當成同一位說話者時不顯示說話者，只改過說話者的片段不標', () => {
    expect(showsAsCorrected(seg('S1', { originalSpeaker: 'S0' }), true)).toBe(false);
    expect(showsAsCorrected(seg('S1', { originalSpeaker: 'S0', text: 'B', originalText: 'A' }), true)).toBe(true);
  });
});

describe('reassignMessage：全部換成另一位之後寫的結果', () => {
  it('寫出換了幾個片段、換成誰', () => {
    expect(reassignMessage(3, 'S0')).toBe('已把 3 個片段換成 S0');
  });
});
