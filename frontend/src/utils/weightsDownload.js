/**
 * 設定頁本機模型權重卡片的下載進度。資料來自後端 GET /setting/local-models/status 的 download：
 *
 *   { state, repo_index, repo_count, current_repo, downloaded_bytes, total_bytes, error }
 *
 * 位元組是這次要下載的所有權重合計。開始下載時後端先問 Hugging Face 每個檔案多大，問完之前
 * total_bytes 是 null。
 */

/**
 * 位元組 → 「850 MB」或「1.4 GB」。用十進位（1 GB = 10^9 位元組），和下載按鈕上的大小
 * （後端 weights.REPO_SIZE_GB）同一種算法，下載完的總數才對得上按鈕寫的。
 */
export function formatWeightsSize(bytes) {
  if (bytes < 1e9) return `${Math.round(bytes / 1e6)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

/** 進度條的百分比與下面那行字。還不知道總共多大時是 0%。 */
export function downloadProgress({ downloaded_bytes: done, total_bytes: total }) {
  if (!total) return { percent: 0, text: '正在向 Hugging Face 確認要下載的檔案…' };
  const downloaded = done ?? 0;
  return {
    // 無條件捨去：還沒下載完就不顯示 100%
    percent: Math.floor((downloaded / total) * 100),
    text: `已下載 ${formatWeightsSize(downloaded)} / ${formatWeightsSize(total)}`,
  };
}
