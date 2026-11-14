import { describe, it, expect } from 'vitest';
import { lastStarted, segmentSpans, segmentsAt, wordAt, wordPieces } from './playhead';

const seg = (start, end, extra = {}) => ({ start, end, ...extra });

describe('segmentSpans：每個片段在時間軸上唸到哪裡', () => {
  it('有結束時間的片段照它寫的', () => {
    expect(segmentSpans([seg(1, 3), seg(4, 6)], 10)).toEqual([
      { start: 1, end: 3 },
      { start: 4, end: 6 },
    ]);
  });

  it('沒有結束時間的片段唸到下一個片段開始（Gemini 沒寫結束的那幾行）', () => {
    expect(segmentSpans([seg(1, null), seg(4, null), seg(9, 12)], 20)).toEqual([
      { start: 1, end: 4 },
      { start: 4, end: 9 },
      { start: 9, end: 12 },
    ]);
  });

  it('最後一段沒有結束時間時唸到音檔結束；不知道音檔多長就一直唸下去', () => {
    expect(segmentSpans([seg(1, 2), seg(5, null)], 30)[1]).toEqual({ start: 5, end: 30 });
    expect(segmentSpans([seg(1, 2), seg(5, null)], null)[1]).toEqual({ start: 5, end: Infinity });
  });

  it('下一段和它同時開始時，唸到再下一個開始得比它晚的片段', () => {
    // 兩位說話者同時開口：同時開始的那段不能讓它的長度變成 0
    expect(segmentSpans([seg(1, null), seg(1, null), seg(3, 5)], 10)).toEqual([
      { start: 1, end: 3 },
      { start: 1, end: 3 },
      { start: 3, end: 5 },
    ]);
  });

  it('結束不比開始晚的片段當成沒有結束時間', () => {
    expect(segmentSpans([seg(2, 2), seg(4, 5)], 10)[0]).toEqual({ start: 2, end: 4 });
  });
});

describe('segmentsAt：播放時間正在唸哪些片段', () => {
  const at = (segments, t, duration = 100) => segmentsAt(segmentSpans(segments, duration), t);

  it('唸到片段的開頭就算，唸到它的結束就不算', () => {
    const segments = [seg(1, 3), seg(3, 6)];
    expect(at(segments, 1)).toEqual([0]);
    expect(at(segments, 2.999)).toEqual([0]);
    expect(at(segments, 3)).toEqual([1]);
  });

  it('第一段之前、片段之間的空檔與最後一段之後都沒有片段', () => {
    const segments = [seg(1, 3), seg(5, 6)];
    expect(at(segments, 0.5)).toEqual([]);
    expect(at(segments, 4)).toEqual([]);
    expect(at(segments, 7)).toEqual([]);
  });

  it('沒有結束時間的片段一直標到下一段開始', () => {
    const segments = [seg(1, null), seg(8, null)];
    expect(at(segments, 7.9)).toEqual([0]);
    expect(at(segments, 8)).toEqual([1]);
    expect(at(segments, 99)).toEqual([1]);
  });

  it('不同說話者重疊時兩段都算，照開始時間排，最晚開口的在最後', () => {
    const segments = [
      seg(0, 10, { speaker: 'S0' }),
      seg(4, 6, { speaker: 'S1' }),
      seg(12, 14, { speaker: 'S0' }),
    ];
    expect(at(segments, 5)).toEqual([0, 1]);
    // S1 講完了，S0 那段還沒結束
    expect(at(segments, 7)).toEqual([0]);
  });

  it('很長的片段蓋過後面好幾段時，後面每一段都還找得到它', () => {
    const segments = [seg(0, 60), seg(5, 6), seg(10, 11), seg(20, 21), seg(30, 31)];
    expect(at(segments, 30.5)).toEqual([0, 4]);
    expect(at(segments, 40)).toEqual([0]);
  });

  it('片段沒照時間排時，回的索引仍是片段在清單裡的位置', () => {
    const segments = [seg(10, 12), seg(1, 3)];
    expect(at(segments, 2)).toEqual([1]);
    expect(at(segments, 11)).toEqual([0]);
  });

  it('上千個片段也找得到', () => {
    const segments = Array.from({ length: 3000 }, (_, i) => seg(i * 2, i * 2 + 1.5));
    expect(at(segments, 4567.2, 7000)).toEqual([2283]);
    expect(at(segments, 4567.7, 7000)).toEqual([]);
  });
});

describe('lastStarted：跟著播放時要捲到的片段', () => {
  const at = (segments, t) => lastStarted(segmentSpans(segments, 100), t);

  it('是最後一個已經開口的片段，重疊時是最晚開口的那段', () => {
    const segments = [seg(0, 10), seg(4, 6), seg(12, 14)];
    expect(at(segments, 5)).toBe(1);
    expect(at(segments, 13)).toBe(2);
  });

  it('片段之間的空檔停在上一段，第一段開始之前是 -1', () => {
    const segments = [seg(1, 3), seg(5, 6)];
    expect(at(segments, 4)).toBe(0);
    expect(at(segments, 0.5)).toBe(-1);
  });
});

describe('wordAt：播放時間正在唸片段裡的哪個字', () => {
  const words = [
    { text: '今', start: 1.0, end: 1.2 },
    { text: '天', start: 1.2, end: 1.5 },
    { text: '好', start: 1.8, end: 2.0 },
  ];

  it('唸到字的開頭就算，唸到它的結束就換下一個', () => {
    expect(wordAt(words, 1.0, 3)).toBe(0);
    expect(wordAt(words, 1.19, 3)).toBe(0);
    expect(wordAt(words, 1.2, 3)).toBe(1);
    expect(wordAt(words, 1.9, 3)).toBe(2);
  });

  it('字和字之間的空檔、第一個字之前與最後一個字之後都沒有字', () => {
    expect(wordAt(words, 0.5, 3)).toBe(-1);
    expect(wordAt(words, 1.6, 3)).toBe(-1);
    expect(wordAt(words, 2.5, 3)).toBe(-1);
  });

  it('沒有結束時間的字唸到下一個字開始，最後一個字唸到片段結束', () => {
    const open = [{ text: '今', start: 1.0 }, { text: '天', start: 1.4, end: null }];
    expect(wordAt(open, 1.3, 2)).toBe(0);
    expect(wordAt(open, 1.9, 2)).toBe(1);
    expect(wordAt(open, 2.0, 2)).toBe(-1);
  });

  it('沒有逐字時間（Gemini 的片段）時沒有字', () => {
    expect(wordAt(null, 1.0, 3)).toBe(-1);
    expect(wordAt([], 1.0, 3)).toBe(-1);
  });
});

describe('wordPieces：片段的文字切成一個個字，標點照樣顯示', () => {
  const words = (...texts) => texts.map((text, i) => ({ text, start: i, end: i + 1 }));

  it('漢字一字一個，標點夾在字之間、不屬於任何字', () => {
    expect(wordPieces('今天，好。', words('今', '天', '好'))).toEqual([
      { text: '今', word: 0 },
      { text: '天', word: 1 },
      { text: '，', word: null },
      { text: '好', word: 2 },
      { text: '。', word: null },
    ]);
  });

  it('假名與英文連在一起的是一個字，空白不屬於任何字', () => {
    expect(wordPieces('これは test です', words('これは', 'test', 'です'))).toEqual([
      { text: 'これは', word: 0 },
      { text: ' ', word: null },
      { text: 'test', word: 1 },
      { text: ' ', word: null },
      { text: 'です', word: 2 },
    ]);
  });

  it('對齊器丟掉字中間的符號（ABC-DEF 是一個字 ABCDEF）時，符號算在那個字裡', () => {
    expect(wordPieces('ABC-DEF！', words('ABCDEF'))).toEqual([
      { text: 'ABC-DEF', word: 0 },
      { text: '！', word: null },
    ]);
  });

  it('一個字不能跨過空白：對齊器在空白斷字，AB CD 是兩個字', () => {
    expect(wordPieces('AB CD', words('ABCD'))).toBeNull();
    expect(wordPieces('AB CD', words('AB', 'CD'))).toEqual([
      { text: 'AB', word: 0 },
      { text: ' ', word: null },
      { text: 'CD', word: 1 },
    ]);
  });

  it('罕用字（兩個 UTF-16 單位）也是一個字', () => {
    expect(wordPieces('𠮷野', words('𠮷', '野'))).toEqual([
      { text: '𠮷', word: 0 },
      { text: '野', word: 1 },
    ]);
  });

  it.each([
    ['文字比逐字時間多一個字', '今天好', ['今', '天']],
    ['逐字時間比文字多一個字', '今天', ['今', '天', '好']],
    ['字對不上（例如改過字或轉成繁體之後）', '今天好', ['今', '夫', '好']],
    ['逐字時間沒有文字', '今天', ['今', null]],
  ])('%s時整段照原樣顯示，不標字', (_, text, texts) => {
    expect(wordPieces(text, texts.map((t, i) => ({ text: t, start: i, end: i + 1 })))).toBeNull();
  });

  it('沒有逐字時間時整段照原樣顯示', () => {
    expect(wordPieces('今天好', null)).toBeNull();
    expect(wordPieces('今天好', [])).toBeNull();
  });
});
