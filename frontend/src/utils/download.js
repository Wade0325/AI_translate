/**
 * 共用的 blob/檔案下載工具。
 */

/**
 * 以 Blob 包裝任意內容後觸發瀏覽器下載。
 *
 * @param {Blob|string} content      下載內容；非 Blob 時會用 text/plain 包裝
 * @param {string} fileName          下載檔名
 * @param {string} [mimeType]        當 content 為字串時使用的 MIME，預設 text/plain;charset=utf-8
 */
export function downloadBlob(content, fileName, mimeType = 'text/plain;charset=utf-8') {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * 把檔名加上指定副檔名（會自動拿掉原檔名最後一個 .xxx）。
 * 例如：renameExtension('foo.mp3', 'srt') => 'foo.srt'
 */
export function renameExtension(fileName, newExt) {
  const stem = fileName.split('.').slice(0, -1).join('.') || fileName;
  return `${stem}.${newExt}`;
}
