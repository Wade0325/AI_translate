/**
 * 轉錄頁記住上次選的供應商與模型（#19）：存在瀏覽器的 localStorage，只有名稱，不含金鑰。
 *
 * 讀不到（沒存過、被清掉、瀏覽器擋下儲存空間、內容壞掉）時當成還沒選，由供應商清單決定預設；
 * 存的供應商或模型已經不在清單上時同樣退回預設，見 utils/providerList.js 的 resolveSelection。
 * 免安裝版換了連接埠（8000 被占用）時，瀏覽器把它當成另一個網站，記住的選擇也會讀不到。
 */

const STORAGE_KEY = 'ai_translate_last_selection';
const NOTHING_CHOSEN = { provider: null, model: null };

const nameOrNull = (value) => (typeof value === 'string' && value ? value : null);

/** 上次選的 { provider, model }；沒有就是 { provider: null, model: null }。 */
export function loadLastSelection() {
  try {
    const saved = JSON.parse(globalThis.localStorage?.getItem(STORAGE_KEY) ?? 'null');
    return { provider: nameOrNull(saved?.provider), model: nameOrNull(saved?.model) };
  } catch {
    return NOTHING_CHOSEN;
  }
}

/**
 * 記下這次選的供應商與模型；存不進去時略過，下次開頁就用預設。
 * @param {{ provider: string | null, model: string | null }} selection
 */
export function saveLastSelection(selection) {
  try {
    // eslint-disable-next-line no-restricted-syntax -- 只存供應商與模型的名稱（例如 local、moss-align），不是金鑰
    globalThis.localStorage?.setItem(
      STORAGE_KEY, JSON.stringify({ provider: selection.provider, model: selection.model }));
  } catch {
    /* 容量滿了或被擋下：不影響這次轉錄 */
  }
}
