/**
 * 校正頁跟著播放（#347）：播放時間正在唸哪些片段、片段裡的哪個字，以及片段的文字怎麼切成一個個字。
 *
 * 時間都是原音檔上的秒數（片段與逐字時間存的就是去靜音前的時間軸）。範圍一律含開頭、不含結束：
 * 唸到下一段的開頭時就換成下一段。
 */

/**
 * @typedef {{ start: number, end?: number | null }} Timed
 * @typedef {{ start: number, end: number }} Span
 * @typedef {{ text?: string | null, start: number, end?: number | null }} Word
 */

/** 結束時間有寫、而且比開始晚，才算有結束時間。 */
function endOf(item) {
  return item.end != null && item.end > item.start ? item.end : null;
}

/** 已排序的數字裡，第一個比 value 大的位置；都不比它大時是 length。 */
function firstAbove(sorted, value) {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] > value) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/**
 * 每個片段在時間軸上唸到哪裡。有結束時間的照它寫的；沒有的（Gemini 沒寫結束的那幾行）唸到下一個
 * 開始得比它晚的片段開始，後面沒有片段時唸到音檔結束，不知道音檔多長時一直唸下去。
 *
 * @param {Timed[]} segments
 * @param {number | null | undefined} duration 音檔長度（秒）
 * @returns {Span[]} 和 segments 一一對應
 */
export function segmentSpans(segments, duration) {
  const starts = segments.map((s) => s.start).sort((a, b) => a - b);
  const last = duration > 0 ? duration : Infinity;
  return segments.map((s) => {
    const end = endOf(s);
    if (end != null) return { start: s.start, end };
    const next = firstAbove(starts, s.start);
    return { start: s.start, end: next < starts.length ? starts[next] : Math.max(last, s.start) };
  });
}

/** segmentsAt 用的索引：片段照開始時間排的順序，以及到每個位置為止最晚的結束。 */
const INDEX = new WeakMap();

function indexOf(spans) {
  let index = INDEX.get(spans);
  if (!index) {
    const order = spans.map((_, i) => i).sort((a, b) => spans[a].start - spans[b].start || a - b);
    const starts = order.map((i) => spans[i].start);
    const latestEnd = [];
    let latest = -Infinity;
    for (const i of order) {
      latest = Math.max(latest, spans[i].end);
      latestEnd.push(latest);
    }
    index = { order, starts, latestEnd };
    INDEX.set(spans, index);
  }
  return index;
}

/**
 * 播放時間 t 正在唸的片段，回的是片段在清單裡的位置。不同說話者重疊時會有好幾個，照開始時間排，
 * 最晚開口的在最後；片段之間的空檔是空陣列。
 *
 * 播放時每一格畫面都會呼叫：先用開始時間找到最後一個已經開始的片段，再往前找到不可能還沒唸完的
 * 地方為止，上千個片段也不必全部看一遍。
 *
 * @param {Span[]} spans segmentSpans 的結果；同一份 spans 只建一次索引
 * @param {number} t
 * @returns {number[]}
 */
export function segmentsAt(spans, t) {
  const { order, starts, latestEnd } = indexOf(spans);
  const active = [];
  for (let k = firstAbove(starts, t) - 1; k >= 0 && latestEnd[k] > t; k -= 1) {
    if (spans[order[k]].end > t) active.push(order[k]);
  }
  return active.reverse();
}

/**
 * 最後一個在 t 之前（含 t）開口的片段，沒有時是 -1。跟著播放時捲到它：片段之間的空檔停在上一段，
 * 不會跳回開頭；不同說話者重疊時是最晚開口的那段。
 *
 * @param {Span[]} spans segmentSpans 的結果
 * @param {number} t
 */
export function lastStarted(spans, t) {
  const { order, starts } = indexOf(spans);
  const k = firstAbove(starts, t) - 1;
  return k >= 0 ? order[k] : -1;
}

/**
 * 播放時間 t 正在唸片段裡的哪個字（逐字時間裡的位置），沒有時是 -1。沒有結束時間的字唸到下一個字
 * 開始，最後一個字唸到片段結束。只有本機的任務有逐字時間；Gemini 的片段沒有，一律是 -1。
 *
 * @param {Word[] | null | undefined} words 照時間排
 * @param {number} t
 * @param {number} segmentEnd 片段唸到哪裡（segmentSpans 的 end）
 */
export function wordAt(words, t, segmentEnd) {
  if (!words?.length) return -1;
  let lo = 0;
  let hi = words.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].start > t) hi = mid;
    else lo = mid + 1;
  }
  const i = lo - 1;
  if (i < 0) return -1;
  const end = endOf(words[i]) ?? (i + 1 < words.length ? words[i + 1].start : segmentEnd);
  return t < end ? i : -1;
}

/** 對齊器算成字的字元：字母（含假名與漢字）、數字與 '（backend/app/services/output_format.py 的 aligner_words）。 */
const WORD_CHAR = /^[\p{L}\p{N}']$/u;

/**
 * 片段的文字切成一段段：逐字時間的每個字一段（word 是它在逐字時間裡的位置），夾在字之間的標點與空白
 * 也各成一段（word 是 null），接起來就是原本的文字。
 *
 * 對齊器斷字時丟掉標點與符號（「ABC-DEF」是一個字「ABCDEF」），所以一個字可以跨過中間的符號。文字和
 * 逐字時間對不上時（字數不同、有字不一樣）回 null，整段照原樣顯示、不標字；下載的輸出格式遇到這種片段
 * 也是整段一行（output_format 的 _words_match）。
 *
 * @param {string | null | undefined} text
 * @param {Word[] | null | undefined} words
 * @returns {{ text: string, word: number | null }[] | null}
 */
export function wordPieces(text, words) {
  if (!text || !words?.length) return null;
  const chars = Array.from(text);
  const pieces = [];
  let pos = 0;
  const gap = (until) => {
    if (until > pos) pieces.push({ text: chars.slice(pos, until).join(''), word: null });
  };

  for (let w = 0; w < words.length; w += 1) {
    const wanted = Array.from(words[w].text ?? '');
    if (!wanted.length) return null;
    let from = -1;
    let at = pos;
    for (const char of wanted) {
      while (at < chars.length && chars[at] !== char) {
        if (WORD_CHAR.test(chars[at])) return null;
        at += 1;
      }
      if (at === chars.length) return null;
      if (from < 0) from = at;
      at += 1;
    }
    gap(from);
    pieces.push({ text: chars.slice(from, at).join(''), word: w });
    pos = at;
  }

  if (chars.slice(pos).some((char) => WORD_CHAR.test(char))) return null;
  gap(chars.length);
  return pieces;
}
