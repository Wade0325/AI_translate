import { normalizedText } from './segmentCorrections';

/**
 * 校正頁的尋找與全部取代（#356）不依賴畫面的部分：怎麼比對、符合的片段、全部取代會改到幾個片段與幾處、上一個與
 * 下一個的順序，以及尋找列的按鍵。
 *
 * 比對的規則和伺服器相同（backend/app/core/text_replacement.py，函式名稱相同），兩邊用同一份案例測試
 * （tests/fixtures/replace_all/cases.json），這裡算的數目就是伺服器實際改到的數目：
 *
 * - 一般文字比對，不支援正規表示式。
 * - 英文不分大小寫：A–Z 和 a–z 當成同一個字，全形的 Ａ–Ｚ 和 ａ–ｚ 也是；全形與半形是不同的字，其他文字照原樣
 *   比對。只換英文字母，換過之後字數不變，找到的位置就是原本文字裡的位置。
 * - 從左到右找，找到的不重疊。
 * - 找的是校正後版本的文字（片段的 text），刪掉的片段不找。
 *
 * @typedef {{ start: number, end: number }} TextRange 一處符合的字在文字裡的位置（[start, end)）
 * @typedef {{ index: number, segKey: string, ranges: TextRange[] }} SegmentMatch
 *   一個符合的片段：它在列表裡的位置、片段鍵，以及每一處符合的字
 * @typedef {{ seg_key: string, text?: string | null, deleted?: boolean }} SearchableSegment
 * @typedef {'next' | 'previous' | 'close'} FindAction 尋找框裡按的鍵要做的事
 */

/** 英文字母換成小寫（半形的 A–Z 換成 a–z，全形的 Ａ–Ｚ 換成 ａ–ｚ），其他字不動（字數不變）。 */
function folded(text) {
  return text.replace(/[A-ZＡ-Ｚ]/g, (char) => String.fromCharCode(char.charCodeAt(0) + 0x20));
}

/**
 * query 在 text 裡出現的每一處，從左到右、不重疊。query 是空的時沒有。
 *
 * @param {string} text
 * @param {string} query
 * @returns {TextRange[]}
 */
export function findOccurrences(text, query) {
  if (!query || !text) return [];
  const haystack = folded(text);
  const needle = folded(query);
  const found = [];
  let at = haystack.indexOf(needle);
  while (at >= 0) {
    found.push({ start: at, end: at + needle.length });
    at = haystack.indexOf(needle, at + needle.length);
  }
  return found;
}

/**
 * 把 text 裡每一處 query 換成 replacement（照打的字放進去），回傳換好的文字與換了幾處。取代的文字裡又含有 query
 * 時不會再換一次。
 *
 * @param {string} text
 * @param {string} query
 * @param {string} replacement
 */
export function replaceOccurrences(text, query, replacement) {
  const found = findOccurrences(text, query);
  let result = '';
  let pos = 0;
  for (const { start, end } of found) {
    result += text.slice(pos, start) + replacement;
    pos = end;
  }
  return { text: found.length ? result + text.slice(pos) : text, count: found.length };
}

/**
 * 有符合的片段，依列表的順序。刪掉的片段不找。
 *
 * @param {SearchableSegment[]} segments 校正後版本的片段
 * @param {string} query
 * @returns {SegmentMatch[]}
 */
export function searchSegments(segments, query) {
  if (!query) return [];
  const matches = [];
  segments.forEach((segment, index) => {
    if (segment.deleted) return;
    const ranges = findOccurrences(segment.text ?? '', query);
    if (ranges.length) matches.push({ index, segKey: segment.seg_key, ranges });
  });
  return matches;
}

/**
 * 全部取代會改到幾個片段、一共幾處，以及其中幾個片段會變成空的（等於刪掉）。取代之後的文字照存的規則收好
 * （normalizedText，和伺服器相同），和現在的文字相同的片段不算：伺服器也不替它們記校正紀錄。
 *
 * @param {SearchableSegment[]} segments 校正後版本的片段
 * @param {string} query
 * @param {string} replacement
 * @returns {{ changedSegments: number, occurrences: number, emptied: number,
 *   changes: { segKey: string, text: string, occurrences: number }[] }}
 */
export function replacementPlan(segments, query, replacement) {
  const changes = [];
  for (const { index, segKey, ranges } of searchSegments(segments, query)) {
    const current = segments[index].text ?? '';
    const text = normalizedText(replaceOccurrences(current, query, replacement).text);
    if (text !== normalizedText(current)) changes.push({ segKey, text, occurrences: ranges.length });
  }
  return {
    changedSegments: changes.length,
    occurrences: changes.reduce((sum, change) => sum + change.occurrences, 0),
    emptied: changes.filter((change) => !change.text).length,
    changes,
  };
}

/**
 * 按了上一個或下一個之後是第幾個符合的片段：到最後一個再按下一個回到第一個，在第一個按上一個跳到最後一個。
 * 沒有符合的片段時是 -1。
 *
 * @param {number} current 現在是第幾個（從 0 起；-1 是還沒有選）
 * @param {number} total 符合的片段數
 * @param {'next' | 'previous'} direction
 */
export function stepMatch(current, total, direction) {
  if (total <= 0) return -1;
  if (current < 0 || current >= total) return direction === 'next' ? 0 : total - 1;
  return direction === 'next' ? (current + 1) % total : (current - 1 + total) % total;
}

/**
 * 一段文字照符合的字切開：每一段標明是不是符合的字，接起來就是原本的文字。offset 是 text 在整個片段文字裡的
 * 開始位置（切逐字時間的一個字時用）。
 *
 * @param {string} text
 * @param {TextRange[]} ranges 整個片段文字裡符合的字，依位置排序
 * @param {number} [offset]
 * @returns {{ text: string, match: boolean }[]}
 */
export function splitByMatches(text, ranges, offset = 0) {
  const parts = [];
  let pos = 0;
  for (const range of ranges) {
    const start = Math.max(range.start - offset, pos);
    const end = Math.min(range.end - offset, text.length);
    if (end <= start) continue;
    if (start > pos) parts.push({ text: text.slice(pos, start), match: false });
    parts.push({ text: text.slice(start, end), match: true });
    pos = end;
  }
  if (pos < text.length) parts.push({ text: text.slice(pos), match: false });
  return parts;
}

/**
 * 校正頁的尋找鍵：Ctrl+F（Mac 是 Command+F）。在校正頁按它開的是頁面自己的尋找：片段列表只畫看得到的那幾列，
 * 瀏覽器內建的尋找找不到沒畫出來的片段。
 *
 * @param {{ key: string, ctrlKey: boolean, metaKey: boolean, altKey: boolean, shiftKey: boolean }} event
 */
export function isFindShortcut(event) {
  return (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'f';
}

/**
 * 尋找框裡按的鍵要做什麼：Enter 下一個、Shift+Enter 上一個、Esc 收起尋找列。輸入法選字中按的鍵一律交給輸入法。
 * 有回動作的鍵，呼叫的人要 preventDefault。
 *
 * @param {{ key: string, shiftKey: boolean, isComposing: boolean, keyCode: number }} event
 * @returns {FindAction | null}
 */
export function findKeyAction(event) {
  if (event.isComposing || event.keyCode === 229) return null;
  if (event.key === 'Enter') return event.shiftKey ? 'previous' : 'next';
  if (event.key === 'Escape') return 'close';
  return null;
}

/**
 * 全部取代之前確認的那一句：會改到幾個片段、一共幾處；有片段會變成空的時另外寫出來（空的片段就是刪掉）。
 *
 * @param {{ changedSegments: number, occurrences: number, emptied: number }} plan replacementPlan 的結果
 */
export function replaceConfirmText({ changedSegments, occurrences, emptied }) {
  const base = `會改到 ${changedSegments} 個片段，一共 ${occurrences} 處。`;
  return emptied ? `${base}其中 ${emptied} 個片段會變成空的，等於刪掉（可以還原）。` : base;
}
