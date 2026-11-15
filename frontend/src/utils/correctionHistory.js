import { revertRequest } from './segmentCorrections';
import { NO_SPEAKER_LABEL } from './speakers';

/**
 * 校正的歷程（#355）不依賴畫面的部分：一個片段的歷程怎麼排、每一版「回到這一版」要送什麼，以及寫給使用者看的字。
 *
 * 歷程讀 GET /transcripts/{task_uuid}/segments/{seg_key}/correction-records（backend/app/api/transcripts.py）。
 * 回到某一版不另開端點：把那一版的內容當成一次普通的校正，用 PATCH 送出（ADR 0011），之前的紀錄都留著，
 * 所以回去之後還能再回來。整批操作用復原一次操作的端點整批復原。
 *
 * @typedef {{ id: number, field: 'text' | 'speaker', old_value: string | null, new_value: string | null,
 *   operation_id: string, created_at: string | null, operation_record_count: number,
 *   operation_segment_count: number }} CorrectionRecord 一筆校正紀錄
 * @typedef {{ seg_key: string, original_text: string, original_speaker: string | null,
 *   records: CorrectionRecord[] }} SegmentCorrectionRecords 一個片段的校正紀錄（後端的回應，紀錄是舊的在前）
 * @typedef {{ kind: 'record', key: string, field: 'text' | 'speaker', before: string | null,
 *   after: string | null, createdAt: string | null, operationId: string, bulk: boolean, segmentCount: number,
 *   current: boolean, request: import('./segmentCorrections').SegmentRequest | null }} RecordEntry
 *   歷程裡的一筆校正紀錄。current：那一項現在的內容就是從這一筆來的（那一項最新的一筆）；request：「回到這一版」
 *   要送的 PATCH body，那一項現在已經是這一版時是 null
 * @typedef {{ kind: 'original', key: 'original', text: string, speaker: string | null, current: boolean,
 *   request: import('./segmentCorrections').SegmentRequest | null }} OriginalEntry
 *   歷程最下面的原始轉錄。current：還沒有任何校正紀錄
 * @typedef {RecordEntry | OriginalEntry} HistoryEntry
 */

/** 「沒有」的寫法和後端相同：文字是空字串，說話者是 null。 */
const EMPTY = { text: '', speaker: null };

/** 比對與送出用的值：「沒有」換成那一項的寫法。 */
function valueOf(field, value) {
  return value ?? EMPTY[field];
}

/**
 * 歷程裡依序列出的每一版：最上面是最新的一筆校正紀錄，最下面是原始轉錄。
 *
 * - 一筆校正紀錄改的是文字或說話者其中一項；回到那一筆，就是把那一項改回它當時的改後。
 * - 回到原始轉錄是文字與說話者都回去，在同一個請求裡送出，後端有變的各記一筆、共用一個操作編號。
 * - 文字與說話者各自最新的一筆就是現在的內容（current），畫面標成「現在」；沒有任何校正紀錄時是原始轉錄。
 *   其他和現在的內容相同的版本（例如回到原始轉錄之後的原始轉錄）沒有要送的（request 是 null）。
 * - 改到超過一個片段的操作（全部取代、把這位說話者全部換成另一位，以及它們的整批復原）是整批操作（bulk），
 *   可以整批復原。一個片段的文字與說話者一起改是兩筆、一個片段，不算。
 * - 整份當成同一位說話者時（#354）不顯示說話者：不列說話者的校正，原始轉錄不帶說話者，回到原始轉錄也只送文字。
 *
 * @param {SegmentCorrectionRecords} history
 * @param {import('./segmentCorrections').Segment} segment 這個片段現在的內容（校正後版本）
 * @param {{ singleSpeaker?: boolean }} [options]
 * @returns {HistoryEntry[]}
 */
export function historyEntries(history, segment, { singleSpeaker = false } = {}) {
  const records = shownRecords(history, singleSpeaker);
  const newest = new Set();
  /** @type {HistoryEntry[]} */
  const entries = [...records].reverse().map((record) => {
    const current = !newest.has(record.field);
    newest.add(record.field);
    const after = valueOf(record.field, record.new_value);
    const same = valueOf(record.field, segment[record.field]) === after;
    return {
      kind: 'record',
      key: String(record.id),
      field: record.field,
      before: record.old_value,
      after: record.new_value,
      createdAt: record.created_at,
      operationId: record.operation_id,
      bulk: record.operation_segment_count > 1,
      segmentCount: record.operation_segment_count,
      current,
      request: same ? null : { [record.field]: after },
    };
  });
  const revert = revertRequest({ ...segment, original_text: history.original_text, original_speaker: history.original_speaker });
  entries.push({
    kind: 'original',
    key: 'original',
    text: valueOf('text', history.original_text),
    speaker: singleSpeaker ? null : valueOf('speaker', history.original_speaker),
    current: records.length === 0,
    request: singleSpeaker ? textOnly(revert) : revert,
  });
  return entries;
}

/**
 * 歷程裡列出的校正紀錄：整份當成同一位說話者時只列文字的（#354）。
 *
 * @param {SegmentCorrectionRecords} history
 * @param {boolean} singleSpeaker
 */
export function shownRecords(history, singleSpeaker) {
  return singleSpeaker ? history.records.filter((record) => record.field === 'text') : history.records;
}

/** 只留下請求裡的文字；沒有文字時是 null。 */
function textOnly(request) {
  return request && 'text' in request ? { text: request.text } : null;
}

/**
 * 歷程裡的改前或改後：文字照寫，空的文字是刪掉這個片段；說話者照寫，沒有說話者寫「未指定」（和片段列相同）。
 *
 * @param {'text' | 'speaker'} field
 * @param {string | null} value
 */
export function valueLabel(field, value) {
  if (field === 'speaker') return value || `（${NO_SPEAKER_LABEL}）`;
  return value || '（刪掉這個片段）';
}

/**
 * 什麼時候改的：後端寫的是伺服器的本地時間（免安裝模式就是這台電腦），顯示成「MM/DD 上午/下午hh:mm:ss」。
 * 同一分鐘裡可能改好幾次，所以寫到秒。沒有或讀不懂時是空字串。
 *
 * @param {string | null | undefined} iso
 */
export function formatRecordTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-TW', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

/**
 * 按了「整批復原」之後寫的結果（給 antd message）。整批操作每個改到的片段各記一筆，所以筆數就是片段數。
 * 只還原那次操作之後沒有再改過的片段；之後又改過的略過，寫出略過了幾個。
 *
 * @param {{ restored: number, skipped: number }} result 復原端點的回應
 * @returns {{ type: 'success' | 'warning', content: string }}
 */
export function bulkUndoMessage({ restored, skipped }) {
  if (!skipped) return { type: 'success', content: `已整批復原 ${restored} 個片段` };
  if (!restored) return { type: 'warning', content: `沒有復原：這 ${skipped} 個片段在這之後都又改過` };
  return { type: 'warning', content: `已整批復原 ${restored} 個片段；略過 ${skipped} 個在這之後又改過的片段` };
}
