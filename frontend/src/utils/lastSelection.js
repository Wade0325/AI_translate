/**
 * 轉錄頁記住上次的選擇：供應商與模型（#19）、Multi-Speaker 開關（#259）、語言（#261）。存在瀏覽器的
 * localStorage，各用一個鍵，只有名稱、開關與語言代碼，不含金鑰。
 *
 * 讀不到（沒存過、被清掉、瀏覽器擋下儲存空間、內容壞掉）時用預設：供應商與模型當成還沒選，由
 * 供應商清單決定；存的供應商或模型已經不在清單上時同樣退回預設，見 utils/providerList.js 的
 * resolveSelection。Multi-Speaker 預設關（#13 Q1）。語言預設 Auto Detect（#13 Q5）；存的語言已經不在
 * 選單上（例如 #14 Q2 拿掉的 zh-CN）時也是。存不進去時略過，下次開頁就用預設。
 * 免安裝版換了連接埠（8000 被占用）時，瀏覽器把它當成另一個網站，記住的選擇也會讀不到。
 */

import { DEFAULT_LANGUAGE, isMenuLanguage } from '../constants/languages.js';

const SELECTION_KEY = 'ai_translate_last_selection';
const MULTI_SPEAKER_KEY = 'ai_translate_last_multi_speaker';
const LANGUAGE_KEY = 'ai_translate_last_language';
const NOTHING_CHOSEN = { provider: null, model: null };

const nameOrNull = (value) => (typeof value === 'string' && value ? value : null);

/** 存在 key 的值（JSON 解析過）；讀不到或壞掉時是 undefined。 */
function readSaved(key) {
  try {
    return JSON.parse(globalThis.localStorage?.getItem(key) ?? 'null') ?? undefined;
  } catch {
    return undefined;
  }
}

/** 把 value 存成 JSON；存不進去時略過。只給這個檔案存名稱、開關與語言代碼，不存金鑰。 */
function writeSaved(key, value) {
  try {
    // eslint-disable-next-line no-restricted-syntax -- 只存供應商與模型的名稱（例如 local、moss-align）、開關與語言代碼，不是金鑰
    globalThis.localStorage?.setItem(key, JSON.stringify(value));
  } catch {
    /* 容量滿了或被擋下：不影響這次轉錄 */
  }
}

/** 上次選的 { provider, model }；沒有就是 { provider: null, model: null }。 */
export function loadLastSelection() {
  const saved = readSaved(SELECTION_KEY);
  if (saved === undefined) return NOTHING_CHOSEN;
  return { provider: nameOrNull(saved?.provider), model: nameOrNull(saved?.model) };
}

/**
 * 記下這次選的供應商與模型。
 * @param {{ provider: string | null, model: string | null }} selection
 */
export function saveLastSelection(selection) {
  writeSaved(SELECTION_KEY, { provider: selection.provider, model: selection.model });
}

/** 上次的 Multi-Speaker 開關；沒存過或讀不到時是關。 */
export function loadLastMultiSpeaker() {
  return readSaved(MULTI_SPEAKER_KEY) === true;
}

/**
 * 記下這次的 Multi-Speaker 開關。
 * @param {boolean} multiSpeaker
 */
export function saveLastMultiSpeaker(multiSpeaker) {
  writeSaved(MULTI_SPEAKER_KEY, multiSpeaker === true);
}

/** 上次選的語言代碼；沒存過、讀不到或已經不在選單上時是 Auto Detect。 */
export function loadLastLanguage() {
  const saved = readSaved(LANGUAGE_KEY);
  return isMenuLanguage(saved) ? saved : DEFAULT_LANGUAGE;
}

/**
 * 記下這次選的語言。
 * @param {string} language 語言選單的 value（例如 'auto'、'ja'）
 */
export function saveLastLanguage(language) {
  writeSaved(LANGUAGE_KEY, language);
}
