/**
 * 轉錄頁送出的請求內容（單檔任務與批次）。純函式，不碰 React 與網路。
 *
 * 每個檔案送出的提示詞，依序取第一個有字的：
 *   1. 檔案卡顯示的提示詞：每檔設定過就是它自己的，沒設定過就是全域的；
 *   2. 供應商的提示詞範本（設定頁）。
 * 都沒有時不帶，由後端用系統預設範本；只有空白算沒填。所選的模型不吃提示詞時一律不帶（#108）。
 */

const blankToNull = (text) => (typeof text === 'string' && text.trim() ? text : null);

/** 跟著全域提示詞：沒在每檔設定填過提示詞。填過（包括清成空白）就用自己的。 */
export const followsGlobalPrompt = (file) => file.prompt === undefined;

/** 每檔設定裡可以編輯的提示詞：跟著全域時是全域的，否則是自己的。 */
export const filePrompt = (file, globalPrompt) =>
  (followsGlobalPrompt(file) ? globalPrompt : file.prompt);

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
 * 語言、說話者與時間戳複製全域當下的值；提示詞清掉，讓檔案跟著全域提示詞走，之後改的也會送出。
 */
export const globalSettingsPatch = (globalConfig) => ({
  language: globalConfig.language,
  isMultiSpeaker: globalConfig.isMultiSpeaker,
  speakerCount: globalConfig.speakerCount,
  prompt: undefined,
  includeTimestamps: globalConfig.includeTimestamps,
  hasOverride: false,
});

/** 這個檔案送出時帶的提示詞（規則見檔頭），檔案卡也照這個顯示；不帶時是 null。 */
export function promptToSend(file, globalPrompt, promptTemplate, supports) {
  if (!supports.prompt) return null;
  return blankToNull(filePrompt(file, globalPrompt)) ?? blankToNull(promptTemplate);
}

/** defaults：全域預設 { sourceLang, multiSpeaker, serviceTier, prompt }，prompt 是全域提示詞。 */
export function buildSinglePayload({ serverFilename, file, provider, model, promptTemplate, defaults, supports, sessionId }) {
  return {
    filename: serverFilename,
    original_filename: file.name,
    provider,
    model,
    source_lang: file.language || defaults.sourceLang,
    prompt: promptToSend(file, defaults.prompt, promptTemplate, supports),
    original_text: supports.userText ? (file.original_text || null) : null,
    multi_speaker: file.isMultiSpeaker ?? defaults.multiSpeaker,
    service_tier: defaults.serviceTier,
    session_id: sessionId,
  };
}

/** files：已經上傳的檔案，各帶 serverFilename；每檔的設定優先於批次層級的備用值。 */
export function buildBatchPayload({ files, provider, model, promptTemplate, defaults, supports, sessionId }) {
  return {
    files: files.map((f) => ({
      filename: f.serverFilename,
      original_filename: f.name,
      file_uid: f.uid,
      source_lang: f.language || defaults.sourceLang,
      prompt: promptToSend(f, defaults.prompt, promptTemplate, supports),
      multi_speaker: f.isMultiSpeaker ?? defaults.multiSpeaker,
    })),
    provider,
    model,
    source_lang: defaults.sourceLang,
    // 後端拿這個值補沒帶提示詞的檔案；只放範本，清成空白的檔案才不會被全域的補回去
    prompt: supports.prompt ? blankToNull(promptTemplate) : null,
    multi_speaker: defaults.multiSpeaker,
    session_id: sessionId,
  };
}
