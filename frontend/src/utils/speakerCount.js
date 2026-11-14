/**
 * 說話者人數（GLOSSARY「說話者人數」，#351、#352）：使用者在轉錄前替一個任務選的說話者數目。
 *
 * 選項是照模型判斷（Auto，預設）或 1 到 8 人；超過 8 人選 Auto。送給後端的值是 'auto' 或 1 到 8 的整數
 * （backend/app/core/speaker_count.py）。選 1 人時整份音檔當成同一位說話者，輸出不帶說話者標記；
 * Auto 與 2 到 8 人時，輸出裡有兩位以上的說話者才帶。Gemini 的提示詞照它寫，本機的模型照舊自己分。
 * 人數是轉錄時用的，轉錄完不能改。
 */

export const AUTO_SPEAKERS = 'auto';
export const MAX_SPEAKERS = 8;

/** 第一次開頁、或記住的值讀不到時的人數（#351 第 1 點）。 */
export const DEFAULT_SPEAKER_COUNT = AUTO_SPEAKERS;

/** Speakers 選單的選項：Auto 與 1 到 8。 */
export const speakerCountOptions = [
  { value: AUTO_SPEAKERS, label: 'Auto' },
  ...Array.from({ length: MAX_SPEAKERS }, (_, i) => ({ value: i + 1, label: String(i + 1) })),
];

/**
 * Speakers 選單一次列出全部選項、不必捲動的高度（antd Select 的 listHeight）：每列 32px（antd 的
 * optionHeight）。預設的 256px 放不下 9 列，選了 3 再打開時 1 會被捲到看不到的地方。
 */
export const SPEAKER_MENU_HEIGHT = speakerCountOptions.length * 32;

/**
 * 是選單上的人數：'auto'，或 1 到 8 的整數。字串的數字與開關的 true／false 都不算。
 * @param {unknown} value
 */
export const isSpeakerCount = (value) =>
  value === AUTO_SPEAKERS || (Number.isInteger(value) && Number(value) >= 1 && Number(value) <= MAX_SPEAKERS);

/**
 * 檔案卡的標籤：Speakers: Auto、Speakers: 3。
 * @param {'auto' | number} value
 */
export const formatSpeakerCount = (value) => `Speakers: ${value === AUTO_SPEAKERS ? 'Auto' : value}`;

/**
 * 選了 2 到 8 人、結果裡的說話者數目卻不同時，結果頁的檔案卡多一行的提醒（#351 第 4 點）；任務照樣完成。
 * 照模型判斷、選 1 人、人數做出來之前的舊任務（沒有記錄所選的人數）、不知道結果有幾位與結果沒有任何一行
 * （speaker_count 是 0，結果頁也不顯示人數）時是 null。
 * @param {unknown} selected 完成時的結果帶的 selected_speaker_count
 * @param {number | null | undefined} actual 完成時的結果帶的 speaker_count
 */
export function speakerCountMismatch(selected, actual) {
  if (!Number.isInteger(selected) || Number(selected) < 2) return null;
  if (!Number.isInteger(actual) || Number(actual) < 1) return null;
  if (actual === selected) return null;
  return `選了 ${selected} 人，結果有 ${actual} 位說話者`;
}
