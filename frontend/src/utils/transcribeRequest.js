/**
 * 轉錄頁送出的請求內容（單檔任務與批次）。純函式，不碰 React 與網路。
 *
 * 每個檔案送出的提示詞，依序取第一個有字的：
 *   1. 檔案卡顯示的提示詞：每檔設定過就是它自己的，沒設定過就是全域的；
 *   2. 供應商的提示詞範本（設定頁）。
 * 都沒有時不帶，由後端用預設範本；只有空白算沒填。所選的模型不吃提示詞時一律不帶（#108）。
 */

const filled = (text) => (typeof text === 'string' && text.trim() ? text : null);

/** 檔案卡顯示、也是送出的提示詞：每檔設定過（包括清成空白）就是它自己的，否則是全域的。 */
export const filePrompt = (file, globalPrompt) => file.prompt ?? globalPrompt;

function promptToSend(file, globalPrompt, promptTemplate, supports) {
  if (!supports.prompt) return null;
  return filled(filePrompt(file, globalPrompt)) ?? filled(promptTemplate);
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
    // 每個檔案都已經帶了自己的提示詞；這是沒帶時的備用值：全域的，沒有就是範本
    prompt: promptToSend({}, defaults.prompt, promptTemplate, supports),
    multi_speaker: defaults.multiSpeaker,
    session_id: sessionId,
  };
}
