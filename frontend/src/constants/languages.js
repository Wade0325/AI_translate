/**
 * 共用語言選項（給 Select / Tag / formatLang 使用）。
 *
 * 抽自原 `components/transcribe/file-config-card.jsx` 內的私有常數，
 * 任何元件想呈現語言選項時都應該 import 此檔。
 */

export const languages = [
  {
    label: 'Common',
    options: [
      { value: 'auto', label: 'Auto Detect' },
      { value: 'zh-TW', label: 'Chinese (Traditional)' },
      { value: 'zh-CN', label: 'Chinese (Simplified)' },
      { value: 'en', label: 'English' },
      { value: 'ja', label: 'Japanese' },
      { value: 'ko', label: 'Korean' },
    ],
  },
  {
    label: 'European',
    options: [
      { value: 'fr', label: 'French' },
      { value: 'de', label: 'German' },
      { value: 'es', label: 'Spanish' },
      { value: 'pt', label: 'Portuguese' },
      { value: 'it', label: 'Italian' },
      { value: 'nl', label: 'Dutch' },
      { value: 'ru', label: 'Russian' },
    ],
  },
  {
    label: 'Other',
    options: [
      { value: 'ar', label: 'Arabic' },
      { value: 'hi', label: 'Hindi' },
      { value: 'th', label: 'Thai' },
      { value: 'vi', label: 'Vietnamese' },
      { value: 'id', label: 'Indonesian' },
    ],
  },
];

/** 將語言 value（例：'zh-TW'）轉成顯示用 label；找不到時回傳原值。*/
export function formatLang(value) {
  for (const group of languages) {
    for (const option of group.options) {
      if (option.value === value) return option.label;
    }
  }
  return value;
}
