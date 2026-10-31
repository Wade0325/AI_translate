import { renameExtension, uniqueFileNames } from './download';
import { localDateKey } from './formatters';

/**
 * 轉錄頁與結果頁的下載：檔案卡上一個已完成的檔案要下載什麼內容、檔名叫什麼，拿不到內容時怎麼
 * 告訴使用者。這裡只算不做，觸發下載與顯示訊息在 hooks/useDownloadBundle.js。
 *
 * 檔案的 result 是完成時廣播的 result.transcripts（utils/fileResult.js），每種輸出格式一個字串。
 * 兩種情況拿不到內容：
 *   - 沒有 result：批次模式完成的檔案（結果存在後端，要到 History 頁面下載），或按取消時任務已經
 *     完成、卻取不回轉錄結果（utils/cancelOutcome.js）
 *   - 這種輸出格式是空字串：後端產生不出這種格式（下載端點回 404 時也當成空字串）
 *
 * @typedef {{ name: string, result?: Record<string, string> | null }} CompletedFile
 * @typedef {{ type: 'success' | 'warning', content: string }} Notice 給 antd message 的訊息
 * @typedef {{ fileName: string, content: string }} Download
 */

const NO_RESULT = 'no-result';
const EMPTY = 'empty';

// 訊息裡最多列出幾個檔名，再多就寫「等 N 個檔案」
const MAX_LISTED_NAMES = 3;

/** 拿不到內容的原因；拿得到時是 null。 */
function missingReason(file, format) {
  if (!file.result) return NO_RESULT;
  if (!file.result[format]) return EMPTY;
  return null;
}

/** 訊息句子的主詞：列出的檔名後面空一格再接中文；檔名太多時改寫「等 N 個檔案」，直接接中文。 */
function subjectOf(names) {
  const listed = names.slice(0, MAX_LISTED_NAMES).join('、');
  return names.length > MAX_LISTED_NAMES ? `${listed} 等 ${names.length} 個檔案` : `${listed} `;
}

/** 依原因分組，說明哪些檔案拿不到這種格式的內容。 */
function describeMissing(files, format) {
  const byReason = (reason) => files.filter((f) => missingReason(f, format) === reason).map((f) => f.name);
  const parts = [];
  const empty = byReason(EMPTY);
  if (empty.length > 0) parts.push(`${subjectOf(empty)}沒有 ${format.toUpperCase()} 內容`);
  const noResult = byReason(NO_RESULT);
  if (noResult.length > 0) parts.push(`${subjectOf(noResult)}的轉錄結果請到 History 頁面下載`);
  return parts.join('；');
}

/**
 * 下載一個檔案的一種輸出格式。拿不到內容時 download 是 null，改顯示 notice，不存出空檔或內容是
 * 「undefined」的檔案。
 *
 * @param {CompletedFile} file
 * @param {string} format 輸出格式（lrc、srt、vtt、txt）
 * @returns {{ download: Download | null, notice: Notice | null }}
 */
export function planFileDownload(file, format) {
  if (missingReason(file, format)) {
    return { download: null, notice: { type: 'warning', content: describeMissing([file], format) } };
  }
  return { download: { fileName: renameExtension(file.name, format), content: file.result[format] }, notice: null };
}

/**
 * 把一組已完成的檔案的同一種輸出格式打包成一個 ZIP。entries 只有拿得到內容的檔案，檔名彼此不撞名
 * （uniqueFileNames）；entries 是空的時候不要產生 ZIP，只顯示 notice。notice 裡的數字是實際打包的
 * 檔案數，沒打包的檔案逐一說明原因。
 *
 * @param {CompletedFile[]} files
 * @param {string} format 輸出格式（lrc、srt、vtt、txt）
 * @param {Date} [now] 決定 ZIP 檔名裡的日期（本地日期）
 * @returns {{ entries: Download[], zipFileName: string, notice: Notice }}
 */
export function planZipDownload(files, format, now = new Date()) {
  const label = format.toUpperCase();
  const packable = files.filter((f) => !missingReason(f, format));
  const names = uniqueFileNames(packable.map((f) => f.name), format);
  const entries = packable.map((f, i) => ({ fileName: names[i], content: f.result[format] }));
  const zipFileName = `transcripts_${label}_${localDateKey(now)}.zip`;

  const missing = files.length > packable.length ? describeMissing(files, format) : '';
  if (entries.length === 0) {
    return { entries, zipFileName, notice: { type: 'warning', content: `沒有可以下載的 ${label} 內容：${missing}` } };
  }
  const packed = `已下載 ${entries.length} 個 ${label} 檔的壓縮包`;
  const notice = missing
    ? { type: /** @type {const} */ ('warning'), content: `${packed}；${missing}` }
    : { type: /** @type {const} */ ('success'), content: packed };
  return { entries, zipFileName, notice };
}
