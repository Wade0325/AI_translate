import { textCorrected } from './segmentCorrections';

/**
 * 校正頁的說話者（#354）不依賴畫面的部分：這個任務現有哪些說話者、選單上可以換成誰、新的說話者編號，以及畫面上
 * 要寫什麼。
 *
 * 說話者編號是 S 加數字（S0、S1…，backend/app/api/transcripts.py 的 _SPEAKER_ID）。改一個片段的說話者用
 * PATCH /transcripts/{task_uuid}/segments/{seg_key}；把這位說話者全部換成另一位用
 * POST /transcripts/{task_uuid}/speakers/reassign，一次操作，可以整批復原。
 *
 * @typedef {import('./segmentCorrections').Segment} Segment
 * @typedef {{ speaker: string, isNew: boolean }} SpeakerChoice 選單上的一個選項；isNew 是新的說話者
 */

/** 沒有說話者的片段在片段列與選單裡的寫法。 */
export const NO_SPEAKER_LABEL = '未指定';

/**
 * 說話者編號的號碼（S12 → 12）；不是 S 加數字時是 null。
 *
 * @param {string | null | undefined} speaker
 */
function speakerNumber(speaker) {
  const match = /^S(\d+)$/.exec(speaker ?? '');
  return match ? Number(match[1]) : null;
}

/** 照號碼排序（S2 在 S10 前面）；不是 S 加數字的排在後面，照字串排。 */
function compareSpeakers(a, b) {
  const [x, y] = [speakerNumber(a), speakerNumber(b)];
  if (x !== null && y !== null) return x - y;
  if (x !== null) return -1;
  if (y !== null) return 1;
  return a.localeCompare(b);
}

/**
 * 這個任務每位說話者有幾個片段：[[說話者編號, 片段數]]，照號碼排序，沒有說話者的片段（null）排在最後。
 *
 * 看校正後的說話者，刪掉的片段也算：它還原之後就是那一位，「全部換成另一位」也會換到它，和後端換的時候同一個範圍。
 * 有片段的說話者就是這個任務現有的說話者。
 *
 * @param {Segment[]} segments
 * @returns {[string | null, number][]}
 */
export function speakerCounts(segments) {
  const counts = new Map();
  for (const segment of segments) {
    const speaker = segment.speaker || null;
    counts.set(speaker, (counts.get(speaker) ?? 0) + 1);
  }
  return [...counts].sort(([a], [b]) => {
    if (a === null || b === null) return a === null ? 1 : -1;
    return compareSpeakers(a, b);
  });
}

/**
 * 選單上可以換成的說話者：現有的其他說話者，最後是新的說話者。
 *
 * @param {string[]} speakers 這個任務現有的說話者（speakerCounts 裡有編號的那些）
 * @param {string | null} current 片段現在的說話者
 * @param {string} nextSpeaker 新的說話者編號
 * @returns {SpeakerChoice[]}
 */
export function speakerChoices(speakers, current, nextSpeaker) {
  return [
    ...speakers.filter((s) => s !== current).map((speaker) => ({ speaker, isNew: false })),
    { speaker: nextSpeaker, isNew: true },
  ];
}

/**
 * 新的說話者編號：這個任務還沒用過的下一個號碼。後端照原始轉錄、校正紀錄與說話者名稱算好給一個（GET 的
 * next_speaker）；之後在頁面上指定了新的說話者，這裡接著往上加。只會變大：指定了又復原的編號在校正紀錄裡用過，
 * 後端也不會再給。
 *
 * @param {string} next 目前的新的說話者編號
 * @param {Segment[]} segments 剛換上的片段
 */
export function nextSpeakerAfter(next, segments) {
  const numbers = segments.map((s) => speakerNumber(s.speaker)).filter((n) => n !== null);
  const after = numbers.length ? Math.max(...numbers) + 1 : 0;
  return `S${Math.max(speakerNumber(next) ?? 0, after)}`;
}

/**
 * 片段那一列寫的說話者：存檔中與失敗時寫送出的說話者，其他時候寫片段現在的說話者。
 *
 * @param {Segment} segment
 * @param {import('./segmentCorrections').SaveState | undefined} save
 * @returns {string | null}
 */
export function shownSpeaker(segment, save) {
  if (save && save.status !== 'saved' && 'speaker' in save.request) return save.request.speaker ?? null;
  return segment.speaker ?? null;
}

/**
 * 要不要標「校正過」。整份當成同一位說話者時頁面不顯示說話者，只改過說話者的片段不標，展開也看不出差在哪裡。
 *
 * @param {Segment} segment
 * @param {boolean} singleSpeaker
 */
export function showsAsCorrected(segment, singleSpeaker) {
  return singleSpeaker ? textCorrected(segment) : segment.corrected;
}

/**
 * 把這位說話者全部換成另一位之後，「復原」旁邊寫的結果。
 *
 * @param {number} changed 改到幾個片段
 * @param {string} toSpeaker 換成哪一位
 */
export function reassignMessage(changed, toSpeaker) {
  return `已把 ${changed} 個片段換成 ${toSpeaker}`;
}
