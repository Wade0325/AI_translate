/**
 * 下載格式的單一來源；各下載 UI 的清單皆由此衍生。
 * key 必須是後端 SubtitleFormats 實際產出的格式（lrc/srt/vtt/txt），
 * 列出後端沒有的格式會讓使用者下載到空內容。
 */
const FORMATS = [
  { key: 'lrc', name: 'LRC', label: 'LRC (Lyrics)', desc: 'Lyrics format' },
  { key: 'srt', name: 'SRT', label: 'SRT (Subtitles)', desc: 'SubRip format with timestamps' },
  { key: 'vtt', name: 'VTT', label: 'VTT (WebVTT)', desc: 'Web Video Text Tracks' },
  { key: 'txt', name: 'TXT', label: 'TXT (Plain Text)', desc: 'Plain text without timestamps' },
];

/** 簡短版（label 為格式名），給 TranscribePage / TaskCard / HistoryPage / file-config-card。 */
export const downloadFormats = FORMATS.map(({ key, name }) => ({ key, label: name }));

/** 帶有「格式」描述後綴的版本，給 Dropdown menu items 使用。 */
export const downloadFormatsLong = FORMATS.map(({ key, name }) => ({ key, label: `${name} 格式` }));

/** Result 頁的完整格式清單（含英文描述），name 供組合語句用。 */
export const downloadFormatsDetailed = FORMATS;
