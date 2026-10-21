/**
 * 供應商清單（後端 GET /providers）的讀取狀態，整個頁面共用一份：任何一處重試成功，
 * 所有用到清單的地方一起更新。
 *
 * 讀取失敗時自動重試，間隔逐次加倍，最多 30 秒；也可以馬上重試（reload）。讀到之後就不再讀。
 * 不碰 React 與網路：怎麼讀（load）與計時器由呼叫端傳進來，hooks/useProviderList.js 接到畫面上。
 */

const RETRY_MAX_MS = 30_000;

/** 第 failures 次失敗之後，等多久再重試。 */
const retryDelayMs = (failures) => Math.min(1000 * 2 ** (failures - 1), RETRY_MAX_MS);

export function createProviderListStore({ load, schedule = setTimeout, cancel = clearTimeout }) {
  let state = { providerList: null, failed: false };
  let failures = 0;
  let loading = null;
  let retryTimer = null;
  const listeners = new Set();

  const update = (next) => {
    state = next;
    listeners.forEach((listener) => listener());
  };

  /** 立刻讀一次（取消排定的自動重試）；正在讀的話不重複讀。回傳這次讀取的 promise。 */
  function reload() {
    if (retryTimer !== null) {
      cancel(retryTimer);
      retryTimer = null;
    }
    if (!loading) {
      loading = load()
        .then(
          (providerList) => {
            failures = 0;
            update({ providerList, failed: false });
          },
          (error) => {
            console.error('讀取供應商清單失敗:', error);
            failures += 1;
            update({ providerList: state.providerList, failed: true });
            retryTimer = schedule(() => {
              retryTimer = null;
              reload();
            }, retryDelayMs(failures));
          },
        )
        .finally(() => {
          loading = null;
        });
    }
    return loading;
  }

  return {
    /** { providerList, failed }：providerList 還沒讀到時是 null；failed 表示上一次讀取失敗。 */
    getSnapshot: () => state,
    /** 第一個用到清單的地方訂閱時開始讀；回傳取消訂閱的函式。 */
    subscribe(listener) {
      listeners.add(listener);
      if (!state.providerList && !loading && retryTimer === null) reload();
      return () => listeners.delete(listener);
    },
    reload,
  };
}
