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

/**
 * 一組音檔打包進同一個 ZIP 時各自的檔名（副檔名換成 newExt），彼此不撞名：撞名的話，解壓縮時
 * 後面的會蓋掉前面的。
 *
 * - 沒有撞名時和單檔下載一樣用 renameExtension：interview.mp3 → interview.srt
 * - 主檔名相同、副檔名不同的音檔保留原本的副檔名來區分：a.mp3 → a.mp3.srt、a.wav → a.wav.srt
 * - 還是撞名（例如同一個檔名上傳了兩次）時，照 Windows 檔案總管的寫法加編號：a.srt、a (2).srt
 *
 * 比對不分大小寫：Windows 的檔案系統不分大小寫，A.srt 與 a.srt 解壓縮到同一個資料夾一樣會互相覆蓋。
 *
 * @param {string[]} fileNames 音檔的檔名，回傳的檔名依同樣的順序
 * @param {string} newExt 輸出格式的副檔名（不含點）
 * @returns {string[]}
 */
export function uniqueFileNames(fileNames, newExt) {
  const renamed = fileNames.map((name) => renameExtension(name, newExt));
  // 換完副檔名之後的每個檔名，各來自哪幾個不同的音檔檔名
  const sources = new Map();
  renamed.forEach((name, i) => {
    const key = name.toLowerCase();
    if (!sources.has(key)) sources.set(key, new Set());
    sources.get(key).add(fileNames[i].toLowerCase());
  });

  const taken = new Set();
  return fileNames.map((fileName, i) => {
    const preferred = sources.get(renamed[i].toLowerCase()).size > 1 ? `${fileName}.${newExt}` : renamed[i];
    const stem = preferred.slice(0, -(newExt.length + 1));
    let name = preferred;
    for (let n = 2; taken.has(name.toLowerCase()); n += 1) {
      name = `${stem} (${n}).${newExt}`;
    }
    taken.add(name.toLowerCase());
    return name;
  });
}
