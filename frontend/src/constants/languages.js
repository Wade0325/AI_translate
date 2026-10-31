/**
 * 共用語言選項（給 Select / Tag / formatLang 使用）；避免各元件各自維護一份。
 *
 * 選單照 ADR-0002 分兩組（#24 的「語言選單分級」）：
 * - 官方支援語言：有評測集把關品質的日文與中文（繁體）。
 * - 未驗證語言：可以選，但沒有評測集把關品質。選了之後，選單收起來的值與檔案卡的標籤也標「未驗證」，
 *   不只在展開的選單裡看得到。
 *
 * Auto Detect 不是一種語言，放在最上面、不屬於任一組（#13 Q5 保留）。
 *
 * 選單沒有 zh-CN（#14 Q2）：中文一律輸出繁體。後端照收舊紀錄與直接呼叫 API 帶的 zh-CN，當成中文、
 * 一樣輸出繁體（backend/app/services/traditional_output.py）；歷史紀錄照常顯示舊任務存的語言代碼。
 */

export const AUTO_DETECT = { value: 'auto', label: 'Auto Detect' };

/** 官方支援語言（officially supported languages）：有評測集把關品質。*/
export const OFFICIAL_LANGUAGES = [
  { value: 'ja', label: 'Japanese' },
  { value: 'zh-TW', label: 'Chinese (Traditional)' },
];

/** 未驗證語言（unverified languages）：可以選，但沒有評測集把關品質。*/
export const UNVERIFIED_LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'ko', label: 'Korean' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
  { value: 'es', label: 'Spanish' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'it', label: 'Italian' },
  { value: 'nl', label: 'Dutch' },
  { value: 'ru', label: 'Russian' },
  { value: 'ar', label: 'Arabic' },
  { value: 'hi', label: 'Hindi' },
  { value: 'th', label: 'Thai' },
  { value: 'vi', label: 'Vietnamese' },
  { value: 'id', label: 'Indonesian' },
];

/** 未驗證語言在選單收起來的值與檔案卡的標籤上加的記號。*/
export const UNVERIFIED_MARK = '未驗證';

/** antd Select 的 options：Auto Detect 在最上面，下面是兩組。*/
export const languages = [
  AUTO_DETECT,
  { label: '官方支援', options: OFFICIAL_LANGUAGES },
  { label: UNVERIFIED_MARK, options: UNVERIFIED_LANGUAGES },
];

/** @param {string} value 語言 value（例：'fr'） */
export function isUnverifiedLanguage(value) {
  return UNVERIFIED_LANGUAGES.some((option) => option.value === value);
}

/**
 * 將語言 value（例：'zh-TW'）轉成顯示用 label；未驗證語言加上「（未驗證）」，例：'French（未驗證）'。
 * 選單裡沒有的值（例：舊的 'zh-CN'）回傳原值。
 * @param {string} value
 */
export function formatLang(value) {
  const option = [AUTO_DETECT, ...OFFICIAL_LANGUAGES, ...UNVERIFIED_LANGUAGES]
    .find((o) => o.value === value);
  if (!option) return value;
  return isUnverifiedLanguage(value) ? `${option.label}（${UNVERIFIED_MARK}）` : option.label;
}
