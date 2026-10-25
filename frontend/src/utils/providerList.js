/**
 * 供應商清單（後端 GET /providers）：供應商、它的模型與每個模型的模型能力。
 *
 *   [{ provider, label, requires_api_key, models: [{ model, label, capabilities }] }]
 *
 * 清單的順序就是畫面的順序：第一個供應商、供應商的第一個模型是預設。畫面依這份清單列出
 * 供應商與模型，依模型能力停用模型不支援的欄位並註明原因，不再寫死哪個供應商有哪些模型、
 * 能用哪些欄位。
 *
 * 端點的欄位只在這個檔案讀，畫面用這裡的函式：tests/integration/test_provider_seam.py 對照
 * 端點，確認這裡讀的欄位端點都有回。還不知道的（清單還沒載入或載入失敗）一律當成支援、
 * 不用金鑰，由後端把關（模型不吃的輸入、模型與供應商對不上，後端都會回明確的錯誤），所以
 * 欄位一改名就會讓畫面默默全部開放，要靠那個測試擋下。
 */

/** provider 是清單上的名稱（例如 local）；查不到時是 null。 */
const findProvider = (providerList, provider) =>
  providerList?.find((p) => p.provider === provider) ?? null;

/** 這個供應商的模型 [{ model, label, capabilities }]；查不到供應商時是空陣列。 */
const providerModels = (providerList, provider) =>
  findProvider(providerList, provider)?.models ?? [];

/** 畫面上的供應商名稱；查不到時直接顯示傳進來的名稱。 */
export const providerLabel = (providerList, provider) =>
  findProvider(providerList, provider)?.label ?? provider;

/** 供應商選單的選項 [{ value, label }]，照清單的順序；清單還沒載入時是空陣列。 */
export const providerOptions = (providerList) =>
  (providerList ?? []).map((p) => ({ value: p.provider, label: p.label }));

/** 這個供應商的模型選單的選項 [{ value, label }]，照清單的順序。 */
export const modelOptions = (providerList, provider) =>
  providerModels(providerList, provider).map((m) => ({ value: m.model, label: m.label }));

/**
 * 選了這個供應商之後用哪個模型：想用的模型（例如設定頁存的預設模型）屬於這個供應商就用它，
 * 否則用這個供應商的預設模型。存的是別的供應商的模型、或已經不在清單上的舊模型，都退回預設，
 * 不會送出供應商與模型對不上的請求。查不到供應商（清單還沒載入）時是 null。
 */
export function modelForProvider(providerList, provider, preferredModel) {
  const models = providerModels(providerList, provider);
  return (models.find((m) => m.model === preferredModel) ?? models[0])?.model ?? null;
}

/**
 * 轉錄頁選的供應商與模型。selection 是使用者選過的 { provider, model }，沒選過的是 null：
 * 還沒選供應商時用清單上的第一個；選的模型不屬於這個供應商（或還沒選）時用它的預設模型。
 */
export function resolveSelection(providerList, selection) {
  const provider = selection.provider ?? providerList?.[0]?.provider ?? null;
  return { provider, model: modelForProvider(providerList, provider, selection.model) };
}

/** 換供應商：模型回到這個供應商的預設模型。 */
export const withProvider = (selection, provider) => ({ ...selection, provider, model: null });

/** 換模型。 */
export const withModel = (selection, model) => ({ ...selection, model });

/**
 * 轉錄要不要使用者的 API 金鑰：要的話，送出前先確認設定頁存了金鑰。也只有要金鑰的供應商
 * 有地方編輯金鑰（設定頁的金鑰欄位、轉錄頁的「編輯 API」），本機沒有。
 */
export const requiresApiKey = (providerList, provider) =>
  findProvider(providerList, provider)?.requires_api_key === true;

/**
 * 按 Start 時缺不缺金鑰：只有要金鑰的供應商才檢查。providerConfig 是設定頁存的設定，
 * 裡面只有遮罩後的金鑰，這裡只確認有存，實際金鑰由後端從資料庫取用。
 */
export const missingApiKey = (providerList, provider, providerConfig) =>
  requiresApiKey(providerList, provider) && !providerConfig?.apiKeys?.[0];

/**
 * 按「測試」送給後端（POST /setting/test）的請求。要金鑰的供應商帶設定頁存的金鑰：那是
 * 遮罩值，後端從資料庫換回實際金鑰；不用金鑰的不帶。
 *
 * 測的是畫面上選的模型 model（設定頁卡片上的、轉錄頁模型選單上的，還沒儲存也算），不是設定頁
 * 存的預設模型。不屬於這個供應商時改測它的預設模型，見 modelForProvider。
 */
export function providerTestRequest(providerList, provider, providerConfig, model) {
  const apiKeys = requiresApiKey(providerList, provider)
    ? (providerConfig?.apiKeys ?? []).filter((key) => key)
    : [];
  return { provider, apiKeys, model: modelForProvider(providerList, provider, model) };
}

/** 這個供應商的這個模型的模型能力；查不到時是 null。 */
export function findModelCapabilities(providerList, provider, model) {
  return providerModels(providerList, provider).find((m) => m.model === model)?.capabilities ?? null;
}

/**
 * 所選模型支援哪些輸入與處理方式：{ prompt, userText, batch, flex, removeSilence }。
 * removeSilence 是轉錄前會不會去靜音；不去靜音的模型照樣拿靜音的位置當切點（#95）。
 * 不支援的輸入送出時不帶上；還不知道模型能力時一律當成支援。
 */
export function modelSupports(capabilities) {
  return {
    prompt: capabilities?.accepts_prompt ?? true,
    userText: capabilities?.accepts_user_text ?? true,
    batch: capabilities?.supports_batch ?? true,
    flex: capabilities?.supports_flex ?? true,
    removeSilence: capabilities?.remove_silence ?? true,
  };
}

/** 停用輸入欄位時顯示的原因（{ prompt, userText }）；支援的那一項是 null。處理模式見 processingModeNote。 */
export function disabledReasonsFor(supports) {
  return {
    prompt: supports.prompt ? null : '所選的模型不支援提示詞，送出時不會帶上',
    userText: supports.userText ? null : '所選的模型不支援使用者文稿，送出時不會帶上',
  };
}

/**
 * 實際用的處理模式（'standard'、'flex' 或 'batch'）：所選的模型不支援使用者選的處理模式時
 * 退回標準，標準每個模型都支援。
 */
export function allowedProcessingMode(mode, supports) {
  return mode === 'standard' || supports[mode] ? mode : 'standard';
}

/** 處理模式選單下方的說明：所選的模型不支援哪些處理模式；都支援時是 null。 */
export function processingModeNote(supports) {
  if (!supports.flex && !supports.batch) return '所選的模型不支援 Flex 與批次，只能用標準';
  if (!supports.flex) return '所選的模型不支援 Flex';
  if (!supports.batch) return '所選的模型不支援批次';
  return null;
}

/**
 * 這個供應商的模型全都不支援提示詞時，回傳停用它的提示詞範本（設定頁與轉錄頁的「編輯參數」）
 * 時顯示的原因；否則是 null。範本由供應商的所有模型共用，所以看全部模型，不看所選的模型。
 */
export function providerPromptDisabledReason(providerList, provider) {
  const models = findProvider(providerList, provider)?.models;
  if (!models || models.some((m) => m.capabilities.accepts_prompt)) return null;
  return '這個供應商的模型都不支援提示詞，提示詞範本不會用到';
}
