/**
 * 供應商清單（後端 GET /providers）：供應商、它的模型與每個模型的模型能力。
 *
 *   [{ provider, label, requires_api_key, models: [{ model, label, capabilities }] }]
 *
 * 清單的順序就是畫面的順序：第一個供應商、供應商的第一個模型是預設。畫面依這份清單列出
 * 供應商與模型，依模型能力停用模型不支援的欄位並註明原因，不再寫死哪個供應商有哪些模型、
 * 能用哪些欄位。
 *
 * 端點的欄位只在這個檔案讀：tests/integration/test_provider_seam.py 對照端點，確認這裡讀的
 * 欄位端點都有回。還不知道的（清單還沒載入或載入失敗）一律當成支援、不用金鑰，由後端把關
 * （模型不吃的輸入、模型與供應商對不上，後端都會回明確的錯誤），所以欄位一改名就會讓畫面
 * 默默全部開放，要靠那個測試擋下。
 */

// 供應商名稱不分大小寫，和後端一致
export const findProvider = (providerList, provider) =>
  providerList?.find((p) => p.provider.toLowerCase() === provider?.toLowerCase()) ?? null;

/** 畫面上的供應商名稱；查不到時直接顯示傳進來的名稱。 */
export const providerLabel = (providerList, provider) =>
  findProvider(providerList, provider)?.label ?? provider;

/** 這個供應商的模型 [{ model, label, capabilities }]；查不到供應商時是空陣列。 */
export const providerModels = (providerList, provider) =>
  findProvider(providerList, provider)?.models ?? [];

/**
 * 選了這個供應商之後用哪個模型：想用的模型（例如設定頁存的預設模型）屬於這個供應商就用它，
 * 否則用這個供應商的預設模型。存的是別的供應商的模型、或已經不在清單上的舊模型，都退回預設，
 * 不會送出供應商與模型對不上的請求。查不到供應商（清單還沒載入）時是 null。
 */
export function modelForProvider(providerList, provider, preferredModel) {
  const models = providerModels(providerList, provider);
  return (models.find((m) => m.model === preferredModel) ?? models[0])?.model ?? null;
}

/** 轉錄要不要使用者的 API 金鑰：要的話，送出前先確認設定頁存了金鑰。 */
export const requiresApiKey = (providerList, provider) =>
  findProvider(providerList, provider)?.requires_api_key === true;

/** 這個供應商的這個模型的模型能力；查不到時是 null。 */
export function findModelCapabilities(providerList, provider, model) {
  return providerModels(providerList, provider).find((m) => m.model === model)?.capabilities ?? null;
}

/**
 * 所選模型支援哪些輸入與處理方式：{ prompt, userText, batch }。
 * 不支援的輸入送出時不帶上；還不知道模型能力時一律當成支援。
 */
export function modelSupports(capabilities) {
  return {
    prompt: capabilities?.accepts_prompt ?? true,
    userText: capabilities?.accepts_user_text ?? true,
    batch: capabilities?.supports_batch ?? true,
  };
}

/** 停用欄位時顯示的原因，鍵和 modelSupports 相同；支援的那一項是 null。 */
export function disabledReasonsFor(supports) {
  return {
    prompt: supports.prompt ? null : '所選的模型不支援提示詞，送出時不會帶上',
    userText: supports.userText ? null : '所選的模型不支援使用者文稿，送出時不會帶上',
    batch: supports.batch ? null : '所選的模型不支援批次，請改用標準',
  };
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
