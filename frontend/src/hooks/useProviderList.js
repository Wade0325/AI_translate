import { useEffect, useState } from 'react';
import { api } from '../services/api';

/**
 * 讀供應商清單（後端 GET /providers）；清單的內容怎麼讀見 utils/providerList.js。
 */

/** 載入失敗時顯示的訊息。 */
export const PROVIDER_LIST_FAILED = '讀取供應商清單失敗，請重新整理頁面';

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

/**
 * { providerList, failed }：providerList 還沒載入或載入失敗時是 null；
 * failed 表示這次載入失敗（重新整理頁面再試）。
 */
export function useProviderList() {
  const [state, setState] = useState({ providerList: null, failed: false });
  useEffect(() => {
    let active = true;
    loadProviderList()
      .then((providerList) => {
        if (active) setState({ providerList, failed: false });
      })
      .catch((error) => {
        console.error('讀取供應商清單失敗:', error);
        if (active) setState({ providerList: null, failed: true });
      });
    return () => {
      active = false;
    };
  }, []);
  return state;
}
