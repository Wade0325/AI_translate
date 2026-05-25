/**
 * 共用格式化工具：時間、檔案大小等顯示用 helper。
 */

/** 把秒數轉成「剛剛 / N 分鐘前 / N 小時前 / N 天前」。 */
export function formatElapsed(seconds) {
  if (!seconds || seconds < 0) return '';
  const m = Math.floor(seconds / 60);
  if (m < 1) return '剛剛';
  if (m < 60) return `${m} 分鐘前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小時前`;
  return `${Math.floor(h / 24)} 天前`;
}

/** ISO/timestamp → zh-TW MM/DD HH:mm；解析失敗時原樣回傳。 */
export function formatDateTime(dateStr) {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleString('zh-TW', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}
