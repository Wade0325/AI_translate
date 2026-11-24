import { describe, it, expect } from 'vitest';
import {
  FLAGGED,
  SPEAKER_UNSURE_BELOW,
  VERIFIED,
  bulkUndoMessage,
  filterCounts,
  cursorAfterSeek,
  hasSpeakerConfidence,
  isSpeakerUnsure,
  isUnseen,
  matchesFilter,
  needsSpeakerCheck,
  nearestVisible,
  reviewProgress,
  reviewToggle,
  stepVisible,
  keysWithoutReviewState,
  visibleIndexes,
} from './reviewStates';

/** 片段裡和確認狀態、進度有關的欄位；沒寫的是沒有確認狀態、沒有校正過。 */
const seg = (key, fields = {}) => ({ seg_key: key, review_state: null, corrected: false, deleted: false, ...fields });

describe('reviewToggle：V 與 F（#349）', () => {
  it.each(/** @type {[any, any, any, boolean][]} */ ([
    [null, VERIFIED, VERIFIED, true],
    [FLAGGED, VERIFIED, VERIFIED, true],
    [null, FLAGGED, FLAGGED, true],
    [VERIFIED, FLAGGED, FLAGGED, true],
  ]))('現在是 %s 時按下標成 %s：標成 %s，換到下一個片段', (now, pressed, next, advance) => {
    expect(reviewToggle(seg('a', { review_state: now }), pressed)).toEqual({ reviewState: next, advance });
  });

  it('已經是已確認時再按一次 V 是取消，留在原地', () => {
    expect(reviewToggle(seg('a', { review_state: VERIFIED }), VERIFIED)).toEqual({ reviewState: null, advance: false });
  });

  it('已經是待查時再按一次 F 是取消，留在原地', () => {
    expect(reviewToggle(seg('a', { review_state: FLAGGED }), FLAGGED)).toEqual({ reviewState: null, advance: false });
  });

  it('校正過的片段沒有自動變成已確認：按 V 照常是標成已確認', () => {
    expect(reviewToggle(seg('a', { corrected: true }), VERIFIED)).toEqual({ reviewState: VERIFIED, advance: true });
  });
});

describe('reviewProgress：已確認或校正過的片段數／全部的片段數', () => {
  it('已確認的與校正過的都算，待查的與還沒看過的不算', () => {
    const segments = [
      seg('verified', { review_state: VERIFIED }),
      seg('corrected', { corrected: true }),
      seg('flagged', { review_state: FLAGGED }),
      seg('untouched'),
    ];
    expect(reviewProgress(segments)).toEqual({ done: 2, total: 4 });
  });

  it('使用者刪掉的片段是校正過的，也算進去', () => {
    expect(reviewProgress([seg('deleted', { corrected: true, deleted: true }), seg('b')])).toEqual({ done: 1, total: 2 });
  });

  it('校正過又標成待查的也算：它已經看過、改過了', () => {
    expect(reviewProgress([seg('a', { corrected: true, review_state: FLAGGED })])).toEqual({ done: 1, total: 1 });
  });

  it('改回原始轉錄之後就不算校正過（後端的 corrected 是 false）', () => {
    expect(reviewProgress([seg('a', { corrected: false })])).toEqual({ done: 0, total: 1 });
  });

  it('沒有片段時是 0／0', () => {
    expect(reviewProgress([])).toEqual({ done: 0, total: 0 });
  });
});

describe('篩選：只看待查的、只看還沒看過的', () => {
  const segments = [
    seg('verified', { review_state: VERIFIED }),
    seg('flagged', { review_state: FLAGGED }),
    seg('corrected', { corrected: true }),
    seg('corrected-and-flagged', { corrected: true, review_state: FLAGGED }),
    seg('untouched'),
  ];

  it('還沒看過：沒有確認狀態，也沒有校正過', () => {
    expect(segments.filter(isUnseen).map((s) => s.seg_key)).toEqual(['untouched']);
  });

  it('只看待查的：校正過的待查片段也在', () => {
    expect(segments.filter((s) => matchesFilter(s, 'flagged')).map((s) => s.seg_key))
      .toEqual(['flagged', 'corrected-and-flagged']);
  });

  it('全部：每個片段都在', () => {
    expect(segments.every((s) => matchesFilter(s, 'all'))).toBe(true);
  });

  it('每種篩選有幾個片段', () => {
    expect(filterCounts(segments)).toEqual({ all: 5, flagged: 2, unseen: 1, unsure: 0 });
  });

  it('列表照篩選只留符合的片段，順序不變', () => {
    expect(visibleIndexes(segments, 'flagged', new Set())).toEqual([1, 3]);
    expect(visibleIndexes(segments, 'unseen', new Set())).toEqual([4]);
    expect(visibleIndexes(segments, 'all', new Set())).toEqual([0, 1, 2, 3, 4]);
  });

  it('選篩選時符合的片段，之後不符合了也留著（例如在待查裡按了 V），不會在眼前消失', () => {
    const kept = new Set(['flagged', 'corrected-and-flagged'])
    const after = segments.map((s) => (s.seg_key === 'flagged' ? { ...s, review_state: VERIFIED } : s));
    expect(visibleIndexes(after, 'flagged', kept)).toEqual([1, 3]);
  });

  it('之後才符合的片段也出現（例如復原了一次校正，它又變回還沒看過）', () => {
    const after = segments.map((s) => (s.seg_key === 'corrected' ? { ...s, corrected: false } : s));
    expect(visibleIndexes(after, 'unseen', new Set(['untouched']))).toEqual([2, 4]);
  });
});

describe('說話者不確定：說話者機率低於門檻', () => {
  const unsure = SPEAKER_UNSURE_BELOW - 0.01;

  it.each([
    [SPEAKER_UNSURE_BELOW - 0.01, true],
    [0, true],
    [SPEAKER_UNSURE_BELOW, false],
    [1, false],
    [null, false],
    [undefined, false],
  ])('說話者機率 %s：說話者不確定是 %s', (confidence, expected) => {
    expect(isSpeakerUnsure(seg('a', { speaker_confidence: confidence }))).toBe(expected);
  });

  it('還沒看過的才要聽：標了確認狀態或校正過（改了說話者、文字，或刪掉）之後就不算', () => {
    expect(needsSpeakerCheck(seg('a', { speaker_confidence: unsure }))).toBe(true);
    expect(needsSpeakerCheck(seg('a', { speaker_confidence: unsure, review_state: VERIFIED }))).toBe(false);
    expect(needsSpeakerCheck(seg('a', { speaker_confidence: unsure, review_state: FLAGGED }))).toBe(false);
    expect(needsSpeakerCheck(seg('a', { speaker_confidence: unsure, corrected: true }))).toBe(false);
    expect(needsSpeakerCheck(seg('a', { speaker_confidence: SPEAKER_UNSURE_BELOW }))).toBe(false);
  });

  it('只看說話者不確定的：列表與篩選上的數字', () => {
    const segments = [
      seg('sure', { speaker_confidence: 0.99 }),
      seg('unsure', { speaker_confidence: unsure }),
      seg('unsure-verified', { speaker_confidence: unsure, review_state: VERIFIED }),
      seg('without-probability'),
      seg('unsure-too', { speaker_confidence: 0.3 }),
    ];
    expect(visibleIndexes(segments, 'unsure', new Set())).toEqual([1, 4]);
    expect(filterCounts(segments)).toEqual({ all: 5, flagged: 0, unseen: 4, unsure: 2 });
  });

  it('在只看說話者不確定的裡按了 V：片段不會在眼前消失，數字少一個', () => {
    const segments = [seg('a', { speaker_confidence: unsure }), seg('b', { speaker_confidence: unsure })];
    const after = [{ ...segments[0], review_state: VERIFIED }, segments[1]];
    expect(visibleIndexes(after, 'unsure', new Set(['a', 'b']))).toEqual([0, 1]);
    expect(filterCounts(after).unsure).toBe(1);
  });

  it('任務有沒有說話者機率：一個片段有就算有（Gemini 與加上說話者機率之前的任務都沒有）', () => {
    expect(hasSpeakerConfidence([seg('a'), seg('b', { speaker_confidence: 1 })])).toBe(true);
    expect(hasSpeakerConfidence([seg('a'), seg('b', { speaker_confidence: null })])).toBe(false);
    expect(hasSpeakerConfidence([])).toBe(false);
  });
});

describe('keysWithoutReviewState：其餘全部標成已確認會標的片段', () => {
  it('還沒有確認狀態的全部（校正過的、刪掉的也在），待查與已確認的不在', () => {
    const segments = [
      seg('verified', { review_state: VERIFIED }),
      seg('flagged', { review_state: FLAGGED }),
      seg('corrected', { corrected: true }),
      seg('deleted', { corrected: true, deleted: true }),
      seg('untouched'),
    ];
    expect(keysWithoutReviewState(segments)).toEqual(['corrected', 'deleted', 'untouched']);
  });
});

describe('bulkUndoMessage：其餘全部標成已確認的復原', () => {
  it('那一次標的都清掉了', () => {
    expect(bulkUndoMessage({ changed: 3 }, 3)).toEqual({ type: 'success', content: '已復原' });
  });

  it('在這之間改了確認狀態的不動，寫出幾個', () => {
    expect(bulkUndoMessage({ changed: 2 }, 3))
      .toEqual({ type: 'warning', content: '已復原；有 1 個片段在這之間改了確認狀態，沒有動' });
  });

  it('全部都在這之間改過了', () => {
    expect(bulkUndoMessage({ changed: 0 }, 2))
      .toEqual({ type: 'warning', content: '這些片段在這之間都改了確認狀態，沒有動' });
  });
});

describe('換片段：↑、↓ 在列表看得到的片段之間移動', () => {
  // 第 1、3 個片段被篩選掉了
  const visible = [0, 2, 4, 5];

  it('下一個、上一個看得到的片段', () => {
    expect(stepVisible(visible, 2, 1)).toBe(4);
    expect(stepVisible(visible, 2, -1)).toBe(0);
  });

  it('已經是最後一個（第一個）時留在原地', () => {
    expect(stepVisible(visible, 5, 1)).toBe(5);
    expect(stepVisible(visible, 0, -1)).toBe(0);
  });

  it('目前的片段看不到時，從它的位置往下、往上找', () => {
    expect(stepVisible(visible, 3, 1)).toBe(4);
    expect(stepVisible(visible, 3, -1)).toBe(2);
  });

  it('還沒有目前的片段時，↓ 從第一個開始', () => {
    expect(stepVisible(visible, -1, 1)).toBe(0);
  });

  it('列表是空的時沒有片段可換', () => {
    expect(stepVisible([], 2, 1)).toBe(-1);
  });

  it('換篩選之後目前的片段看不到時，換到它後面最近的；後面沒有就前面最近的', () => {
    expect(nearestVisible(visible, 3)).toBe(4);
    expect(nearestVisible(visible, 6)).toBe(5);
    expect(nearestVisible(visible, 2)).toBe(2);
    expect(nearestVisible([], 2)).toBe(-1);
  });
});

describe('followPlayback：目前的片段跟著播放', () => {
  const spans = [{ start: 0, end: 2 }, { start: 2, end: 4 }, { start: 2, end: 3 }, { start: 5, end: 7 }];
  const everyone = () => true;

  it('拖到的位置還在目前的片段裡時不換', () => {
    expect(cursorAfterSeek(spans, 1.5, 0, everyone)).toBe(0);
  });

  it('拖到別的片段時換過去', () => {
    expect(cursorAfterSeek(spans, 6, 1, everyone)).toBe(3);
  });

  it('同時開始的片段：拖到它們的開頭時，留在原本選到的那一個', () => {
    expect(cursorAfterSeek(spans, 2, 1, everyone)).toBe(1);
  });

  it('拖到片段之間的空檔時換到前面那一段', () => {
    expect(cursorAfterSeek(spans, 4.5, 3, everyone)).toBe(2);
  });

  it('拖到列表看不到的片段（被篩選掉了）時，留在原本的片段', () => {
    expect(cursorAfterSeek(spans, 6, 1, (i) => i !== 3)).toBe(1);
  });

  it('拖到第一個片段開始之前時不換', () => {
    expect(cursorAfterSeek([{ start: 1, end: 2 }], 0, 0, everyone)).toBe(0);
  });
});
