import { textCorrected } from './segmentCorrections';

/**
 * 校正頁的說話者（#354）不依賴畫面的部分：這個任務現有哪些說話者、選單上可以換成誰、新的說話者編號，以及畫面上
 * 要寫什麼。
 *
 * 說話者編號是 S 加數字（S0、S1…，backend/app/api/transcripts.py 的 _SPEAKER_ID）。改一個片段的說話者用
 * PATCH /transcripts/{task_uuid}/segments/{seg_key}；把這位說話者全部換成另一位用
 * POST /transcripts/{task_uuid}/speakers/reassign，一次操作，可以整批復原。
 *
 * 說話者名稱（#359）：替說話者編號取的名字，每個任務各取各的，用
 * PUT /transcripts/{task_uuid}/speakers/{speaker}/name 設定或清掉，算一次校正，可以復原。畫面上取了名字的說話者寫名稱，
 * 沒取的寫編號。
 *
 * @typedef {import('./segmentCorrections').Segment} Segment
 * @typedef {{ speaker: string, isNew: boolean }} SpeakerChoice 選單上的一個選項；isNew 是新的說話者
 * @typedef {Record<string, string>} SpeakerNames 這個任務的說話者名稱：{說話者編號: 名稱}，只列取了名字的
 */

/** 沒有說話者的片段在片段列與選單裡的寫法。 */
export const NO_SPEAKER_LABEL = '未指定';

/** 說話者名稱最多幾個字（去掉前後的空白之後算；backend/app/api/transcripts.py 的 SPEAKER_NAME_MAX_LENGTH）。 */
export const SPEAKER_NAME_MAX_LENGTH = 30;

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
 * @param {SpeakerNames} [names]
 */
export function reassignMessage(changed, toSpeaker, names = {}) {
  return sentence('已把', changed, '個片段換成', speakerText(toSpeaker, names));
}

/**
 * 把幾段字接成一句中文：接縫的一邊是英數字時空一格，兩邊都是中文時不空，例如「S0 的 3 個片段」、「王小明的 3 個片段」。
 * 說話者編號是英數字、名稱多半是中文，句子裡寫說話者的地方用它接，取了名字之後中文不會多出空格。
 *
 * @param {...(string | number)} parts
 */
export function sentence(...parts) {
  return parts.map(String).reduce((out, part) => {
    if (!out || !part) return out + part;
    return /[A-Za-z0-9]$/.test(out) || /^[A-Za-z0-9]/.test(part) ? `${out} ${part}` : out + part;
  }, '');
}

/**
 * 片段那一列寫的說話者（#359）：取了名字的寫名稱，沒取的寫說話者編號，沒有說話者的寫「未指定」。
 *
 * @param {string | null} speaker
 * @param {SpeakerNames} names
 */
export function speakerText(speaker, names) {
  if (!speaker) return NO_SPEAKER_LABEL;
  return names[speaker] || speaker;
}

/**
 * 說話者選單上一個選項的寫法：取了名字的寫「名稱（編號）」，同名的人不會有，但編號讓人對得上下載的原始轉錄；
 * 沒取的寫編號；新的說話者寫「新的說話者（編號）」。
 *
 * @param {SpeakerChoice} choice
 * @param {SpeakerNames} names
 */
export function choiceLabel(choice, names) {
  if (choice.isNew) return `新的說話者（${choice.speaker}）`;
  const name = names[choice.speaker];
  return name ? `${name}（${choice.speaker}）` : choice.speaker;
}

/**
 * 名稱哪裡不合規則，給取名字的輸入框馬上寫出來；合規則時是 null。和後端同一套規則（backend/app/api/transcripts.py 的
 * _speaker_name），存的時候後端還會再擋一次，同一個任務裡重複的名稱也由後端擋。前後的空白不算，空的是清掉名稱。
 * 輸入框只有一行，打不出換行。
 *
 * @param {string} draft 輸入框裡的字
 * @returns {string | null}
 */
export function speakerNameProblem(draft) {
  const name = draft.trim();
  if (Array.from(name).length > SPEAKER_NAME_MAX_LENGTH) return `名稱最多 ${SPEAKER_NAME_MAX_LENGTH} 個字`;
  if (/[[\]]/.test(name)) return '名稱不能有方括號（[ 或 ]）';
  const key = name.normalize('NFKC');
  if (/^s[0-9]+$/i.test(key)) return '名稱不能寫成 S 加數字，會和說話者編號分不出來';
  if (/^[0-9]+:[0-9]+(?:[.:][0-9]+)?$/.test(key)) return '名稱不能寫成時間（例如 00:05.00），LRC 會把它當成時間戳';
  return null;
}

/**
 * 取名字之後，「復原」旁邊寫的結果。
 *
 * @param {string} speaker 說話者編號
 * @param {string | null} name 現在的名稱；清掉時是 null
 */
export function renameMessage(speaker, name) {
  return name ? `已把 ${speaker} 叫做「${name}」` : `${speaker} 已改回顯示說話者編號`;
}
