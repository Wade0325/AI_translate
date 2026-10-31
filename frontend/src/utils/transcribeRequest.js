/**
 * 轉錄頁送出的請求內容（單檔任務與批次）。純函式，不碰 React 與網路。
 *
 * 轉錄頁填的提示詞是補充說明：後端把它空一行接在提示詞範本後面送出（#144）。範本是設定頁為供應商
 * 存的（沒存過就是系統內建的），後端派送時自己從設定讀，請求裡不帶範本。
 *
 * 每個檔案送出的補充說明：這個檔案自己的提示詞（每檔設定）；沒有自己的（沒填過，或清空、只剩空白）
 * 就跟著全域的。都沒有時不帶，後端只送範本；只有空白算沒填。所選的模型不吃提示詞時一律不帶（#108）。
 */

const blankToNull = (text) => (typeof text === 'string' && text.trim() ? text : null);

/** 跟著全域提示詞：這個檔案沒有自己的提示詞（沒填過，或清空、只剩空白）。 */
export const followsGlobalPrompt = (file) => blankToNull(file.prompt) === null;

/** 這個檔案用的提示詞：跟著全域時是全域的，否則是自己的。 */
export const filePrompt = (file, globalPrompt) =>
  (followsGlobalPrompt(file) ? globalPrompt : file.prompt);

/**
 * 重新轉錄：把已經結束的檔案改回等待處理，清掉上一次的結果與送出的提示詞。每檔設定照舊，
 * 所以之後送出的提示詞照現在的設定算。
 */
export const forRetranscription = (file) => ({
  ...file,
  status: 'waiting',
  percent: 0,
  tokens_used: 0,
  cost: 0,
  result: null,
  statusText: '等待處理',
  task_uuid: null,
  error: null,
  failure: null,
  sentPrompt: undefined,
});

/**
 * 按 Start 時的全域預設（buildSinglePayload／buildBatchPayload 的 defaults）：檔案沒有每檔
 * 設定的欄位用它補上。globalPrompt 是轉錄頁的全域提示詞；processingMode 是 'standard'、
 * 'flex' 或 'batch'，只有 Flex 要帶 service_tier。
 */
export const requestDefaults = ({ language, multiSpeaker, processingMode, globalPrompt }) => ({
  sourceLang: language,
  multiSpeaker,
  serviceTier: processingMode === 'flex' ? 'flex' : null,
  prompt: globalPrompt,
});

/**
 * 把一個檔案的每檔設定改回全域預設（Apply to All、Reset to global）時要更新的欄位。
 * 語言與 Multi-Speaker 複製全域當下的值；提示詞清掉，讓檔案跟著全域提示詞走，之後改的也會送出。
 */
export const globalSettingsPatch = (globalConfig) => ({
  language: globalConfig.language,
  isMultiSpeaker: globalConfig.isMultiSpeaker,
  prompt: undefined,
  hasOverride: false,
});

/**
 * 這個檔案送出時帶的補充說明（規則見檔頭），檔案卡也照這個顯示；不帶時是 null。提示詞範本每次都送，
 * 不是這個檔案的設定，不算在裡面。
 */
export function promptToSend(file, globalPrompt, supports) {
  if (!supports.prompt) return null;
  return blankToNull(filePrompt(file, globalPrompt));
}

/** defaults：全域預設 { sourceLang, multiSpeaker, serviceTier, prompt }，prompt 是全域提示詞。 */
export function buildSinglePayload({ serverFilename, file, provider, model, defaults, supports, sessionId }) {
  return {
    filename: serverFilename,
    original_filename: file.name,
    provider,
    model,
    source_lang: file.language || defaults.sourceLang,
    prompt: promptToSend(file, defaults.prompt, supports),
    user_supplied_text: supports.userText ? (file.userSuppliedText || null) : null,
    multi_speaker: file.isMultiSpeaker ?? defaults.multiSpeaker,
    service_tier: defaults.serviceTier,
    session_id: sessionId,
  };
}

/**
 * files：已經上傳的檔案，各帶 serverFilename；每檔的設定優先於批次層級的備用值。批次層級不帶提示詞：
 * 每個檔案已經帶了自己要送的補充說明（後端拿批次層級的補沒帶的檔案，沒有就只送範本）。
 */
export function buildBatchPayload({ files, provider, model, defaults, supports, sessionId }) {
  return {
    files: files.map((f) => ({
      filename: f.serverFilename,
      original_filename: f.name,
      file_uid: f.uid,
      source_lang: f.language || defaults.sourceLang,
      prompt: promptToSend(f, defaults.prompt, supports),
      multi_speaker: f.isMultiSpeaker ?? defaults.multiSpeaker,
    })),
    provider,
    model,
    source_lang: defaults.sourceLang,
    multi_speaker: defaults.multiSpeaker,
    session_id: sessionId,
  };
}
