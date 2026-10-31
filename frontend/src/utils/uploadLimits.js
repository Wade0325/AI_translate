/**
 * 上傳格式與大小（後端 GET /upload/limits，清單只寫在 backend/app/core/upload_formats.py，#258）：
 * 檔案選擇器收哪些副檔名、上傳區的說明文字，以及加入檔案時當場擋下伺服器不會收的檔案。
 *
 * limits 的形狀：{ formats: [{ extension: '.mp3', label: 'MP3', kind: 'audio' | 'video' }], max_bytes }。
 * 規則和伺服器相同：只看副檔名（瀏覽器給的 MIME 類型常是空的或對不上），大小不超過 max_bytes。
 * 伺服器上傳時會再檢查一次，這裡只是讓使用者不必等上傳完才知道。
 */

/** 檔名的副檔名，小寫、帶點；沒有副檔名時是空字串。 */
function extensionOf(name) {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot).toLowerCase() : '';
}

/** 某一類（audio、video）的格式名稱，用頓號接起來，例如「MP3、WAV」。 */
export function formatLabels(limits, kind) {
  return limits.formats.filter((f) => f.kind === kind).map((f) => f.label).join('、');
}

/**
 * 位元組 → 「2 GB」「2.1 GB」「1.5 MB」：1 GB 以上寫 GB、以下寫 MB（以 1024 進位），無條件進位到一位
 * 小數，整數不帶小數。和伺服器的訊息同一種寫法；剛超過上限的檔案不會寫成和上限一樣大。
 */
export function sizeLabel(bytes) {
  const unit = bytes >= 1024 ** 3 ? 1024 ** 3 : 1024 ** 2;
  const tenths = Math.ceil((bytes * 10) / unit);
  const size = tenths % 10 === 0 ? String(tenths / 10) : (tenths / 10).toFixed(1);
  return `${size} ${unit === 1024 ** 3 ? 'GB' : 'MB'}`;
}

/** 大小上限，寫法見 {@link sizeLabel}，例如「2 GB」。 */
export function maxSizeLabel(limits) {
  return sizeLabel(limits.max_bytes);
}

/** 檔案選擇器的 accept：列出的副檔名，例如「.mp3,.wav,.mp4」。 */
export function acceptAttribute(limits) {
  return limits.formats.map((f) => f.extension).join(',');
}

/**
 * 伺服器收不收這個檔案：收的話回傳 null，不收的話回傳給使用者看的原因（帶檔名，一次加入好幾個
 * 檔案時看得出是哪一個）。file 是瀏覽器的 File（只用 name 與 size）。
 */
export function rejectionOf(file, limits) {
  const extension = extensionOf(file.name);
  if (!limits.formats.some((f) => f.extension === extension)) {
    return `不支援這種格式：${file.name}（音檔可以用 ${formatLabels(limits, 'audio')}；`
      + `影片可以用 ${formatLabels(limits, 'video')}）`;
  }
  if (file.size <= 0) return `檔案是空的：${file.name}`;
  if (file.size > limits.max_bytes) {
    return `檔案太大：${file.name}（${sizeLabel(file.size)}，上限 ${maxSizeLabel(limits)}）`;
  }
  return null;
}
