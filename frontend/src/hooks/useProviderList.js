import { useSyncExternalStore } from 'react';
import { api } from '../services/api';
import { createProviderListStore } from '../utils/providerListStore';

/**
 * 讀供應商清單（後端 GET /providers）；清單的內容怎麼讀見 utils/providerList.js。
 */

/** 讀取失敗時顯示的訊息；會自動重試，也可以按「重試」。 */
export const PROVIDER_LIST_FAILED = '讀取供應商清單失敗，正在自動重試';

// 整個頁面共用一份：任何一處重試成功，用到清單的元件一起更新
const store = createProviderListStore({ load: () => api.providers() });

/**
 * { providerList, failed, reload }：providerList 還沒讀到時是 null；failed 表示上一次讀取
 * 失敗、正在等自動重試；reload 立刻重試。
 */
export function useProviderList() {
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return { ...state, reload: store.reload };
}
