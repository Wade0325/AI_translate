import { renameExtension, uniqueFileNames } from './download';
import { localDateKey } from './formatters';
import { CORRECTED } from './transcriptVersions';

/**
 * 轉錄頁與結果頁的下載：檔案卡上一個已完成的檔案要下載什麼內容、檔名叫什麼，拿不到內容時怎麼
 * 告訴使用者。觸發下載與顯示訊息在 hooks/useDownloadBundle.js。
 *
 * 內容一律向下載端點（GET /history/{task_uuid}/download/{fmt}）拿校正後版本（#346），不用完成時
 * 送到畫面的內容（檔案的 result，存在瀏覽器的記憶體裡）：使用者在校正頁改過之後，從這裡下載的才不會是
 * 校正前的內容。沒有校正的任務，校正後版本就是原始轉錄。拿不到內容的原因有四種：
 *   - no-task：檔案沒有任務紀錄的 id。批次模式完成的檔案（轉錄頁只知道批次結束了），要到 History 頁面下載
 *   - empty：後端產生不出這種格式（下載端點回 404，任務紀錄還在）
 *   - deleted：任務紀錄已經被刪掉（下載端點回 404，任務紀錄也查不到）；只有 History 頁面刪得掉任務紀錄
 *   - failed：連不上伺服器，或其他錯誤
 *
 * @typedef {{ name: string, task_uuid?: string }} CompletedFile
 * @typedef {'no-task' | 'empty' | 'deleted' | 'failed'} MissingReason
 * @typedef {{ file: CompletedFile, content?: string, missing?: MissingReason }} Fetched 下載端點拿到的結果：
 *   content 與 missing 只有一個
 * @typedef {{ type: 'success' | 'warning', content: string }} Notice 給 antd message 的訊息
 * @typedef {{ fileName: string, content: string }} Download
 */

/** 拿不到內容的原因各自怎麼說；句子的主詞是檔名（見 subjectOf），依這個順序排。 */
const MISSING_TEXT = {
  empty: (format) => `沒有 ${format.toUpperCase()} 內容`,
  'no-task': () => '的轉錄結果請到 History 頁面下載',
  deleted: () => '的任務紀錄已經在 History 刪掉了，下載不到轉錄結果',
  failed: () => '下載失敗，請稍後再試',
};

// 訊息裡最多列出幾個檔名，再多就寫「等 N 個檔案」
const MAX_LISTED_NAMES = 3;

/**
 * 向下載端點拿每個檔案那種格式的校正後版本，依 files 的順序回傳。不會丟出例外：拿不到內容的檔案帶著原因。
 * 下載端點對「沒有任務紀錄」與「產生不出這種格式」都回 404，所以 404 時再查一次任務紀錄分辨是哪一種。
 *
 * @param {CompletedFile[]} files
 * @param {string} format 輸出格式（lrc、srt、vtt、txt）
 * @param {{ history: { get: Function, downloadTranscript: Function } }} api services/api.js 的 api，測試換成假的
 * @returns {Promise<Fetched[]>}
 */
export function fetchTranscripts(files, format, api) {
  return Promise.all(files.map((file) => fetchOne(file, format, api)));
}

/**
 * @param {CompletedFile} file
 * @param {string} format
 * @param {{ history: { get: Function, downloadTranscript: Function } }} api
 * @returns {Promise<Fetched>}
 */
async function fetchOne(file, format, api) {
  if (!file.task_uuid) return { file, missing: 'no-task' };
  try {
    const content = await api.history.downloadTranscript(file.task_uuid, format, { version: CORRECTED });
    return content ? { file, content } : { file, missing: 'empty' };
  } catch (error) {
    if (error?.status !== 404) return { file, missing: 'failed' };
    return { file, missing: await notFoundReason(file.task_uuid, api) };
  }
}

/**
 * 下載端點回 404 的原因：任務紀錄還在就是產生不出這種格式，查不到就是被刪掉了。
 *
 * @param {string} taskUuid
 * @param {{ history: { get: Function } }} api
 * @returns {Promise<MissingReason>}
 */
async function notFoundReason(taskUuid, api) {
  try {
    await api.history.get(taskUuid);
    return 'empty';
  } catch (error) {
    return error?.status === 404 ? 'deleted' : 'failed';
  }
}

/** 訊息句子的主詞：列出的檔名後面空一格再接中文；檔名太多時改寫「等 N 個檔案」，直接接中文。 */
function subjectOf(names) {
  const listed = names.slice(0, MAX_LISTED_NAMES).join('、');
  return names.length > MAX_LISTED_NAMES ? `${listed} 等 ${names.length} 個檔案` : `${listed} `;
}

/** 依原因分組，說明哪些檔案拿不到這種格式的內容。 */
function describeMissing(fetched, format) {
  return Object.entries(MISSING_TEXT)
    .map(([reason, text]) => [fetched.filter((f) => f.missing === reason).map((f) => f.file.name), text])
    .filter(([names]) => names.length > 0)
    .map(([names, text]) => `${subjectOf(names)}${text(format)}`)
    .join('；');
}

/**
 * 下載一個檔案的一種輸出格式。拿不到內容時 download 是 null，改顯示 notice，不存出空檔或內容是
 * 「undefined」的檔案。
 *
 * @param {Fetched} fetched fetchTranscripts 拿到的結果
 * @param {string} format 輸出格式（lrc、srt、vtt、txt）
 * @returns {{ download: Download | null, notice: Notice | null }}
 */
export function planFileDownload(fetched, format) {
  if (fetched.missing) {
    return { download: null, notice: { type: 'warning', content: describeMissing([fetched], format) } };
  }
  return { download: { fileName: renameExtension(fetched.file.name, format), content: fetched.content }, notice: null };
}

/**
 * 把一組已完成的檔案的同一種輸出格式打包成一個 ZIP。entries 只有拿得到內容的檔案，檔名彼此不撞名
 * （uniqueFileNames）；entries 是空的時候不要產生 ZIP，只顯示 notice。notice 裡的數字是實際打包的
 * 檔案數，沒打包的檔案逐一說明原因。
 *
 * @param {Fetched[]} fetched fetchTranscripts 拿到的結果
 * @param {string} format 輸出格式（lrc、srt、vtt、txt）
 * @param {Date} [now] 決定 ZIP 檔名裡的日期（本地日期）
 * @returns {{ entries: Download[], zipFileName: string, notice: Notice }}
 */
export function planZipDownload(fetched, format, now = new Date()) {
  const label = format.toUpperCase();
  const packable = fetched.filter((f) => !f.missing);
  const names = uniqueFileNames(packable.map((f) => f.file.name), format);
  const entries = packable.map((f, i) => ({ fileName: names[i], content: f.content }));
  const zipFileName = `transcripts_${label}_${localDateKey(now)}.zip`;

  const missing = fetched.length > packable.length ? describeMissing(fetched, format) : '';
  if (entries.length === 0) {
    return { entries, zipFileName, notice: { type: 'warning', content: `沒有可以下載的 ${label} 內容：${missing}` } };
  }
  const packed = `已下載 ${entries.length} 個 ${label} 檔的壓縮包`;
  const notice = missing
    ? { type: /** @type {const} */ ('warning'), content: `${packed}；${missing}` }
    : { type: /** @type {const} */ ('success'), content: packed };
  return { entries, zipFileName, notice };
}
