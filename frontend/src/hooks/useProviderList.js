import { useEffect, useState } from 'react';
import { api } from '../services/api';

/**
 * 供應商、它們的模型與每個模型的模型能力（後端 GET /providers）。
 *
 * 畫面依模型能力停用模型不支援的欄位並註明原因，不再寫死哪個供應商能用哪些欄位。
 * 還沒載入或載入失敗時一律當成「支援」：欄位照常可填、照常送出，由後端把關
 * （模型不吃的輸入，後端會回明確的錯誤）。
 *
 * 模型能力的欄位只在這個檔案讀：tests/integration/test_provider_seam.py 會對照端點，
 * 確認這裡讀的欄位端點都有回，欄位改名時不會讓畫面默默全部開放。
 */

// 整個頁面共用一次請求；失敗時清掉，下次掛載再試
let providerListRequest = null;

function loadProviderList() {
  if (!providerListRequest) {
    providerListRequest = api.providers().catch((error) => {
      providerListRequest = null;
      throw error;
    });
  }
  return providerListRequest;
}

/** [{ provider, models: [{ model, capabilities }] }]；還沒載入或載入失敗時是 null。 */
export function useProviderList() {
  const [providerList, setProviderList] = useState(null);
  useEffect(() => {
    let active = true;
    loadProviderList()
      .then((list) => {
        if (active) setProviderList(list);
      })
      .catch((error) => console.error('讀取模型能力失敗:', error));
    return () => {
      active = false;
    };
  }, []);
  return providerList;
}

// 供應商名稱不分大小寫：畫面用 Google／Local，端點回 google／local
const findProvider = (providerList, provider) =>
  providerList?.find((p) => p.provider.toLowerCase() === provider?.toLowerCase());

/** 這個供應商的這個模型的模型能力；查不到時是 null。 */
export function findModelCapabilities(providerList, provider, model) {
  const models = findProvider(providerList, provider)?.models;
  return models?.find((m) => m.model === model)?.capabilities ?? null;
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
