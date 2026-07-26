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

/** 秒數 → 「H:MM:SS」或「M:SS」。 */
export function formatDuration(seconds) {
  if (!seconds) return '0:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const ss = String(Math.floor(seconds % 60)).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** ISO/timestamp → zh-TW MM/DD HH:mm；解析失敗時原樣回傳。 */
export function formatDateTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  // Invalid Date 不會 throw（toLocaleString 會直接回傳 "Invalid Date" 字串），需明確檢查
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleString('zh-TW', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Date → 本地日期字串 YYYY-MM-DD。
 * 後端 /history/usage 的 daily[].date 是伺服器本地日期（DB func.now() 寫入本地時間），
 * 前後端同機部署，所以用瀏覽器本地日期即可對齊；勿改用 toISOString()（那是 UTC）。
 */
export function localDateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** 圖表 Y 軸 token 刻度：1.2M / 12k / 3.5k / 400。 */
export function formatTokensTick(v) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 10_000) return `${Math.round(v / 1000)}k`;
  if (v >= 1_000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}
