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
