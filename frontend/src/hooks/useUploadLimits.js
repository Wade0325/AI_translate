import { useEffect, useState } from 'react';
import { api } from '../services/api';

// 整個頁面共用一次讀取：清單在 app 執行期間不會變。讀取失敗時清掉，下次用到時再讀
let loading = null;

function load() {
  if (!loading) {
    loading = api.uploadLimits().catch((error) => {
      loading = null;
      throw error;
    });
  }
  return loading;
}

/**
 * 上傳格式與大小（後端 GET /upload/limits，見 utils/uploadLimits.js）。還沒讀到、讀不到時是 null：
 * 這時不在加入檔案時先擋，交給伺服器上傳時檢查。
 */
export function useUploadLimits() {
  const [limits, setLimits] = useState(null);

  useEffect(() => {
    let current = true;
    load()
      .then((loaded) => { if (current) setLimits(loaded); })
      .catch((error) => console.error('讀取上傳格式與大小失敗:', error));
    return () => { current = false; };
  }, []);

  return limits;
}
