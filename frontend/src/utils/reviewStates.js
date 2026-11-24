import { lastStarted } from './playhead';

/**
 * 校正頁的確認狀態、進度與篩選（#349，#345 第 6 節）不依賴畫面的部分。
 *
 * 確認狀態（review_state）由使用者自己標，分已確認與待查，和校正互不影響：校正過的片段不會自動變成已確認，
 * 還原校正也不會動到確認狀態。它不是校正，不留校正紀錄。
 *
 * 「目前這個片段」是快捷鍵（↑、↓、Enter、V、F、R）作用的片段，用片段在清單裡的位置表示，沒有時是 -1。它是
 * 「下一個要處理的片段」，不是播放位置：只在換片段（↑、↓，以及 V、F 標完）、點一列、拖播放進度時換，播放往下
 * 走時不跟著換。一路聽下去時，聽完一段才按 V，播放已經進到下一段，V 照樣標剛聽完的那一段（#25 故事 64）。
 *
 * 說話者不確定（GLOSSARY 的說話者機率）：模型寫這個片段的說話者時給它的機率低於門檻，表示模型拿不定是誰說的。
 * 還沒看過的這種片段可以單獨篩出來，只聽這幾句、不必整份聽完。
 *
 * @typedef {'verified' | 'flagged'} ReviewState
 * @typedef {{ seg_key: string, review_state?: string | null, corrected: boolean, deleted?: boolean,
 *   speaker_confidence?: number | null }} ReviewedSegment
 *   片段裡和確認狀態、進度有關的欄位（GET /transcripts/{task_uuid} 的片段）
 * @typedef {'all' | 'flagged' | 'unseen' | 'unsure'} ReviewFilter
 *   列表的篩選：全部、只看待查的、只看還沒看過的、只看說話者不確定的
 */

/** 已確認。 */
export const VERIFIED = 'verified';
/** 待查。 */
export const FLAGGED = 'flagged';

/**
 * 按 V（標成已確認）或 F（標成待查）之後片段的確認狀態，以及要不要換到下一個片段：已經是那個狀態時再按一次是
 * 取消（清掉），留在原地；其他時候標上去，換到下一個片段。
 *
 * @param {ReviewedSegment} segment
 * @param {ReviewState} pressed
 * @returns {{ reviewState: ReviewState | null, advance: boolean }}
 */
export function reviewToggle(segment, pressed) {
  if (segment.review_state === pressed) return { reviewState: null, advance: false };
  return { reviewState: pressed, advance: true };
}

/**
 * 片段算進進度：已確認，或校正過（文字或說話者和原始轉錄不同，包括使用者刪掉的片段）。確認狀態和校正是兩回事，
 * 只是進度兩種都算。
 *
 * @param {ReviewedSegment} segment
 */
function countsTowardProgress(segment) {
  return segment.review_state === VERIFIED || segment.corrected;
}

/**
 * 頁面上方的進度：已確認或校正過的片段數／全部的片段數。
 *
 * @param {ReviewedSegment[]} segments
 */
export function reviewProgress(segments) {
  return { done: segments.filter(countsTowardProgress).length, total: segments.length };
}

/**
 * 還沒看過的片段：沒有確認狀態，也沒有校正過。
 *
 * @param {ReviewedSegment} segment
 */
export function isUnseen(segment) {
  return !segment.review_state && !segment.corrected;
}

/**
 * 說話者不確定的門檻：說話者機率低於這個值的片段算說話者不確定。
 */
export const SPEAKER_UNSURE_BELOW = 0.9;

/**
 * 說話者不確定：模型寫這個片段的說話者時，給它的機率（說話者機率，speaker_confidence）低於門檻。沒有說話者機率的
 * 片段（Gemini、VibeVoice、加上說話者機率之前轉錄的任務）不算。
 *
 * @param {ReviewedSegment} segment
 */
export function isSpeakerUnsure(segment) {
  const confidence = segment.speaker_confidence;
  return typeof confidence === 'number' && confidence < SPEAKER_UNSURE_BELOW;
}

/**
 * 要聽一下是誰說的片段：說話者不確定，而且還沒看過。標了確認狀態（V 或 F）、改了說話者（或文字、刪掉）之後就不算：
 * 聽過了。
 *
 * @param {ReviewedSegment} segment
 */
export function needsSpeakerCheck(segment) {
  return isSpeakerUnsure(segment) && isUnseen(segment);
}

/**
 * 這個任務有沒有說話者機率（本機的 MOSS 轉錄的才有）：沒有時不給「只看說話者不確定的」。
 *
 * @param {ReviewedSegment[]} segments
 */
export function hasSpeakerConfidence(segments) {
  return segments.some((s) => typeof s.speaker_confidence === 'number');
}

/**
 * @param {ReviewedSegment} segment
 * @param {ReviewFilter} filter
 */
export function matchesFilter(segment, filter) {
  if (filter === 'flagged') return segment.review_state === FLAGGED;
  if (filter === 'unseen') return isUnseen(segment);
  if (filter === 'unsure') return needsSpeakerCheck(segment);
  return true;
}

/**
 * 每種篩選現在有幾個片段（篩選的選項上寫的數字）。
 *
 * @param {ReviewedSegment[]} segments
 * @returns {Record<ReviewFilter, number>}
 */
export function filterCounts(segments) {
  return {
    all: segments.length,
    flagged: segments.filter((s) => matchesFilter(s, 'flagged')).length,
    unseen: segments.filter(isUnseen).length,
    unsure: segments.filter(needsSpeakerCheck).length,
  };
}

/**
 * 列表留下哪些片段（在清單裡的位置，照原本的順序）：符合篩選的，加上選這個篩選時就符合的（kept，片段鍵）。
 * 後者在這之後不符合了也留著，例如在「只看待查的」裡按了 V：片段不會在眼前消失，再按一次 V 也還取消得到。
 * 要重新篩選就再選一次篩選。
 *
 * @param {ReviewedSegment[]} segments
 * @param {ReviewFilter} filter
 * @param {Set<string>} kept
 * @returns {number[]}
 */
export function visibleIndexes(segments, filter, kept) {
  const visible = [];
  segments.forEach((segment, i) => {
    if (matchesFilter(segment, filter) || kept.has(segment.seg_key)) visible.push(i);
  });
  return visible;
}

/**
 * 「其餘全部標成已確認」會標的片段：還沒有確認狀態的全部，校正過的與刪掉的也在；已經標成待查的不動。
 *
 * @param {ReviewedSegment[]} segments
 */
export function keysWithoutReviewState(segments) {
  return segments.filter((s) => !s.review_state).map((s) => s.seg_key);
}

/**
 * 「其餘全部標成已確認」的復原之後寫的結果（給 antd message）。復原只清掉那一次標的片段裡現在還是已確認的；
 * 在這之間被改成待查（或清掉）的不動，寫出幾個。
 *
 * @param {{ changed: number }} result 一次改很多個片段的確認狀態的端點的回應
 * @param {number} marked 那一次標了幾個
 * @returns {{ type: 'success' | 'warning', content: string }}
 */
export function bulkUndoMessage({ changed }, marked) {
  if (changed >= marked) return { type: 'success', content: '已復原' };
  if (!changed) return { type: 'warning', content: '這些片段在這之間都改了確認狀態，沒有動' };
  return { type: 'warning', content: `已復原；有 ${marked - changed} 個片段在這之間改了確認狀態，沒有動` };
}

/**
 * ↑、↓（以及 V、F 標完之後）換到哪個片段：列表看得到的片段裡，目前這個片段的下一個（direction 是 1）或上一個
 * （-1）。已經是最後一個（第一個）時留在原地；目前的片段看不到時，從它的位置往下、往上找。列表是空的時是 -1。
 *
 * @param {number[]} visible 列表看得到的片段在清單裡的位置，由小到大
 * @param {number} current 目前這個片段在清單裡的位置，沒有時是 -1
 * @param {1 | -1} direction
 */
export function stepVisible(visible, current, direction) {
  if (!visible.length) return -1;
  if (direction > 0) return visible.find((i) => i > current) ?? (visible.includes(current) ? current : visible.at(-1));
  // tsconfig 的 lib 是 ES2022，還沒有 findLast
  const before = visible.filter((i) => i < current);
  return before.length ? before[before.length - 1] : (visible.includes(current) ? current : visible[0]);
}

/**
 * 換篩選之後，目前這個片段看不到時換到哪個片段：它後面最近的看得到的片段，後面沒有就前面最近的。
 *
 * @param {number[]} visible 由小到大
 * @param {number} current
 */
export function nearestVisible(visible, current) {
  if (!visible.length) return -1;
  return visible.find((i) => i >= current) ?? visible.at(-1);
}

/**
 * 拖播放進度到 time 之後，目前這個片段是哪一個：time 還在目前的片段裡時不換（同時開始的片段，選到的那一個才不會
 * 被換掉）；跑出去了就換到那裡正在播放的片段（最後一個在 time 之前開口的，見 playhead.js 的 lastStarted），它在
 * 列表看不到（被篩選掉了）時留在原本的片段。
 *
 * 只在使用者拖播放進度時呼叫：播放往下走、←、→ 倒退前進都不換目前的片段（見檔頭）。
 *
 * @param {import('./playhead').Span[]} spans segmentSpans 的結果
 * @param {number} time 播放位置（秒）
 * @param {number} current
 * @param {(index: number) => boolean} isVisible
 */
export function cursorAfterSeek(spans, time, current, isVisible) {
  const span = spans[current];
  if (span && span.start <= time && time < span.end) return current;
  const playing = lastStarted(spans, time);
  return playing >= 0 && isVisible(playing) ? playing : current;
}
