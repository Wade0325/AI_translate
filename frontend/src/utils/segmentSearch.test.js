import { describe, it, expect } from 'vitest';
// 伺服器的整合測試（tests/integration/test_transcripts_api.py 的 TestReplaceAll）用同一份案例
import sharedCases from '../../../tests/fixtures/replace_all/cases.json?raw';
import {
  findKeyAction,
  findOccurrences,
  isFindShortcut,
  replaceConfirmText,
  replaceOccurrences,
  replacementPlan,
  searchSegments,
  splitByMatches,
  stepMatch,
} from './segmentSearch';

/** 一個片段；text 是空的就是刪掉的片段（和 GET /transcripts 回的一樣）。 */
const seg = (segKey, text) => ({ seg_key: segKey, text, deleted: !text.trim() });
const segmentsOf = (...texts) => texts.map((text, i) => seg(String(i).padStart(4, '0'), text));

/** 鍵盤事件裡用得到的欄位；沒寫的是沒按、不在選字。 */
const key = (k, fields = {}) => ({
  key: k, shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, isComposing: false, keyCode: 0, ...fields,
});

describe('全部取代的數目和伺服器一致（和整合測試共用的案例）', () => {
  /** @type {{ name: string, texts: string[], find: string, replacement: string,
   *   expected: { changed_segments: number, occurrences: number, texts: string[] } }[]} */
  const cases = JSON.parse(sharedCases);

  it('案例檔讀得到', () => {
    expect(cases.length).toBeGreaterThan(5);
  });

  it.each(cases.map((c) => [c.name, c]))('%s', (_name, c) => {
    const segments = segmentsOf(...c.texts);

    const plan = replacementPlan(segments, c.find, c.replacement);

    expect([plan.changedSegments, plan.occurrences]).toEqual([c.expected.changed_segments, c.expected.occurrences]);
    // 改到的片段換成算出來的文字之後，就是伺服器存的校正後版本
    const byKey = new Map(plan.changes.map((change) => [change.segKey, change.text]));
    expect(segments.map((s) => (byKey.has(s.seg_key) ? byKey.get(s.seg_key) : s.text))).toEqual(c.expected.texts);
  });
});

describe('findOccurrences：一般文字比對（#356）', () => {
  it('英文不分大小寫，位置是原本文字裡的位置', () => {
    expect(findOccurrences('Mimiji 和 MIMIJI', 'mimiji')).toEqual([{ start: 0, end: 6 }, { start: 9, end: 15 }]);
  });

  it('全形與半形是不同的字；全形英文字母也不分大小寫，其他文字照原樣比對', () => {
    expect(findOccurrences('ＡＩ 和 ａｉ', 'AI')).toEqual([]);
    expect(findOccurrences('ＡＩ 和 ａｉ', 'ａＩ')).toEqual([{ start: 0, end: 2 }, { start: 5, end: 7 }]);
    expect(findOccurrences('Ä 和 ä', 'ä')).toEqual([{ start: 4, end: 5 }]);
  });

  it('不支援正規表示式', () => {
    expect(findOccurrences('1.5 和 135', '1.5')).toEqual([{ start: 0, end: 3 }]);
    expect(findOccurrences('a+b', '.')).toEqual([]);
  });

  it('從左到右、不重疊', () => {
    expect(findOccurrences('啊啊啊', '啊啊')).toEqual([{ start: 0, end: 2 }]);
  });

  it('要找的是空的時沒有', () => {
    expect(findOccurrences('今天', '')).toEqual([]);
  });
});

describe('replaceOccurrences', () => {
  it('照打的字放進去，不跟著原本的大小寫；不會再換一次', () => {
    expect(replaceOccurrences('MIMIJI 和 mimiji', 'mimiji', 'Mimiji')).toEqual({ text: 'Mimiji 和 Mimiji', count: 2 });
    expect(replaceOccurrences('小明', '小明', '王小明')).toEqual({ text: '王小明', count: 1 });
  });
});

describe('searchSegments：符合的片段', () => {
  it('依列表的順序，刪掉的片段不找', () => {
    const segments = segmentsOf('王曉明先說', '', '下一位', '謝謝王曉明，王曉明');

    expect(searchSegments(segments, '王曉明')).toEqual([
      { index: 0, segKey: '0000', ranges: [{ start: 0, end: 3 }] },
      { index: 3, segKey: '0003', ranges: [{ start: 2, end: 5 }, { start: 6, end: 9 }] },
    ]);
  });

  it('刪掉的片段只有空白也不找', () => {
    expect(searchSegments([{ seg_key: 'a', text: '  ', deleted: true }], ' ')).toEqual([]);
  });
});

describe('replacementPlan：會改到幾個片段、幾處', () => {
  it('取代之後和現在相同的片段不算', () => {
    const plan = replacementPlan(segmentsOf('Mimiji', 'MIMIJI 和 mimiji'), 'mimiji', 'Mimiji');

    expect([plan.changedSegments, plan.occurrences]).toEqual([1, 2]);
    expect(plan.changes.map((c) => c.segKey)).toEqual(['0001']);
  });

  it('寫出幾個片段會變成空的', () => {
    const plan = replacementPlan(segmentsOf('嗯', '嗯，好的', '好的'), '嗯', '');

    expect([plan.changedSegments, plan.occurrences, plan.emptied]).toEqual([2, 2, 1]);
  });
});

describe('stepMatch：上一個、下一個的順序', () => {
  it('下一個依序往後，最後一個之後回到第一個', () => {
    expect(stepMatch(0, 3, 'next')).toBe(1);
    expect(stepMatch(1, 3, 'next')).toBe(2);
    expect(stepMatch(2, 3, 'next')).toBe(0);
  });

  it('上一個依序往前，第一個之前跳到最後一個', () => {
    expect(stepMatch(2, 3, 'previous')).toBe(1);
    expect(stepMatch(0, 3, 'previous')).toBe(2);
  });

  it('還沒有選時，下一個是第一個、上一個是最後一個；沒有符合的片段時是 -1', () => {
    expect(stepMatch(-1, 3, 'next')).toBe(0);
    expect(stepMatch(-1, 3, 'previous')).toBe(2);
    expect(stepMatch(5, 3, 'next')).toBe(0);
    expect(stepMatch(0, 0, 'next')).toBe(-1);
  });
});

describe('splitByMatches：標出符合的字', () => {
  it('接起來就是原本的文字', () => {
    expect(splitByMatches('謝謝王曉明，王曉明', [{ start: 2, end: 5 }, { start: 6, end: 9 }])).toEqual([
      { text: '謝謝', match: false },
      { text: '王曉明', match: true },
      { text: '，', match: false },
      { text: '王曉明', match: true },
    ]);
  });

  it('切逐字時間的一個字時，只取落在這個字裡的那一段', () => {
    // 片段文字「Hello world」裡符合「lo wo」（3–8），切的是第二個字「world」（從 6 開始）
    expect(splitByMatches('world', [{ start: 3, end: 8 }], 6)).toEqual([
      { text: 'wo', match: true },
      { text: 'rld', match: false },
    ]);
    expect(splitByMatches('Hello', [{ start: 3, end: 8 }], 0)).toEqual([
      { text: 'Hel', match: false },
      { text: 'lo', match: true },
    ]);
  });

  it('沒有符合的字時整段照原樣', () => {
    expect(splitByMatches('今天', [])).toEqual([{ text: '今天', match: false }]);
  });
});

describe('尋找的按鍵', () => {
  it('Ctrl+F 與 Command+F 開頁面自己的尋找；只按 F 或加了其他鍵的不算', () => {
    expect(isFindShortcut(key('f', { ctrlKey: true }))).toBe(true);
    expect(isFindShortcut(key('F', { ctrlKey: true }))).toBe(true);
    expect(isFindShortcut(key('f', { metaKey: true }))).toBe(true);
    expect(isFindShortcut(key('f'))).toBe(false);
    expect(isFindShortcut(key('f', { ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isFindShortcut(key('f', { ctrlKey: true, altKey: true }))).toBe(false);
  });

  it('尋找框裡 Enter 下一個、Shift+Enter 上一個、Esc 收起來；選字中的鍵交給輸入法', () => {
    expect(findKeyAction(key('Enter'))).toBe('next');
    expect(findKeyAction(key('Enter', { shiftKey: true }))).toBe('previous');
    expect(findKeyAction(key('Escape'))).toBe('close');
    expect(findKeyAction(key('a'))).toBeNull();
    expect(findKeyAction(key('Enter', { isComposing: true }))).toBeNull();
    expect(findKeyAction(key('Enter', { keyCode: 229 }))).toBeNull();
  });
});

describe('replaceConfirmText', () => {
  it('寫明會改到幾個片段、一共幾處；有片段會變成空的時另外寫出來', () => {
    expect(replaceConfirmText({ changedSegments: 2, occurrences: 3, emptied: 0 })).toBe('會改到 2 個片段，一共 3 處。');
    expect(replaceConfirmText({ changedSegments: 2, occurrences: 2, emptied: 1 }))
      .toBe('會改到 2 個片段，一共 2 處。其中 1 個片段會變成空的，等於刪掉（可以還原）。');
  });
});
