/**
 * 共用下載格式定義；前端各下載 UI（TranscribePage、TaskPage、file-config-card）
 * 都引用此檔，避免散落多份相同清單。
 */

export const downloadFormats = [
  { key: 'lrc', label: 'LRC' },
  { key: 'srt', label: 'SRT' },
  { key: 'vtt', label: 'VTT' },
  { key: 'txt', label: 'TXT' },
];

/** 帶有「格式」描述後綴的版本，給 Dropdown menu items 使用。 */
export const downloadFormatsLong = downloadFormats.map((item) => ({
  ...item,
  label: `${item.label} 格式`,
}));

/** Result 頁的完整格式清單（含 JSON 與英文描述），name 供組合語句用。 */
export const downloadFormatsDetailed = [
  { key: 'srt', name: 'SRT', label: 'SRT (Subtitles)', desc: 'SubRip format with timestamps' },
  { key: 'vtt', name: 'VTT', label: 'VTT (WebVTT)', desc: 'Web Video Text Tracks' },
  { key: 'txt', name: 'TXT', label: 'TXT (Plain Text)', desc: 'Plain text without timestamps' },
  { key: 'json', name: 'JSON', label: 'JSON (Structured)', desc: 'Structured data with metadata' },
  { key: 'lrc', name: 'LRC', label: 'LRC (Lyrics)', desc: 'Lyrics format' },
];
