import { downloadFormats } from '../constants/downloadFormats';
import { renameExtension } from './download';

/**
 * 下載的兩個版本（#346）：校正後版本（預設）與原始轉錄。值是下載端點的 version 參數
 * （backend/app/services/output_format.py 的 Version）。
 *
 * @typedef {'corrected' | 'original'} TranscriptVersion
 * @typedef {{ key: string, label: string, type?: 'group', children?: MenuItem[] }} MenuItem antd Menu 的項目
 */

/** @type {TranscriptVersion} */
export const CORRECTED = 'corrected';
/** @type {TranscriptVersion} */
export const ORIGINAL = 'original';

const VERSION_LABELS = { [CORRECTED]: '校正後版本', [ORIGINAL]: '原始轉錄' };

/**
 * 下載的檔名：音檔的檔名換上輸出格式的副檔名；原始轉錄多一段 .original，例如 會議.srt 是校正後版本、
 * 會議.original.srt 是原始轉錄。和下載端點的 Content-Disposition 同一個規則（backend/app/api/history.py）。
 *
 * @param {string} audioName 音檔的檔名
 * @param {string} format 輸出格式（lrc、srt、vtt、txt）
 * @param {TranscriptVersion} version
 */
export function transcriptFileName(audioName, format, version) {
  return renameExtension(audioName, version === ORIGINAL ? `original.${format}` : format);
}

/**
 * 選單項目的 key 帶著版本與輸出格式，見 {@link downloadTarget}。
 *
 * @param {TranscriptVersion} version
 * @returns {MenuItem[]}
 */
const formatItems = (version) => downloadFormats.map((f) => ({ key: `${version}:${f.key}`, label: f.label }));

/**
 * History 一列的下載選單（antd Menu 的 items）。沒有校正的任務和以前一樣只列四種輸出格式，下載的是
 * 校正後版本（沒有校正時就是原始轉錄），不多看到用不到的選項；有校正的任務分成「校正後版本」與
 * 「原始轉錄」兩組，各有四種輸出格式。
 *
 * @param {boolean} hasCorrections 任務有沒有校正紀錄（History 清單的 has_corrections）
 * @returns {MenuItem[]}
 */
export function downloadMenuItems(hasCorrections) {
  if (!hasCorrections) return formatItems(CORRECTED);
  return [CORRECTED, ORIGINAL].map((version) => ({
    key: version,
    type: 'group',
    label: VERSION_LABELS[version],
    children: formatItems(version),
  }));
}

/**
 * 點了的選單項目要下載什麼。
 *
 * @param {string} key {@link downloadMenuItems} 的項目 key
 * @returns {{ version: TranscriptVersion, format: string }}
 */
export function downloadTarget(key) {
  const [version, format] = key.split(':');
  return { version: /** @type {TranscriptVersion} */ (version), format };
}
