import { ApiError } from '../services/api';

/**
 * 校正頁（#347）用到的固定內容：網址、播放速度，以及不能校正時寫給使用者看的一句話。
 */

/** react-router 的路徑：網址帶任務 id，重新整理或之後再回來都開得到。 */
export const CORRECTION_PATH = '/correction/:taskUuid';

/** @param {string} taskUuid */
export function correctionPath(taskUuid) {
  return `/correction/${taskUuid}`;
}

/** 播放列的速度選項（倍）。 */
export const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2];

/**
 * 不能校正的原因（後端 app/services/correctability.py 的 Uncorrectable）→ 校正頁寫的那一句。各種原因
 * 都只寫一句、不出錯：使用者可能是從舊的書籤或別處貼來的網址開的。
 */
const REASON_MESSAGES = {
  not_completed: '這個任務還沒完成，完成之後才能校正。',
  no_segments: '這個任務沒有可以逐段校正的片段（較早版本轉錄的任務只存了整份轉錄結果），轉錄結果仍可以在 History 下載。',
  translation: '這是翻譯的任務，翻譯結果不能校正。',
};

const NOT_FOUND = '找不到這個任務，可能已經在 History 刪掉了。';
const UNREADABLE = '讀不到這個任務，請確認 Mimiji 還在執行，再重新整理一次。';

/**
 * 校正頁開不起來時的說明：讀取失敗時給 error，讀到了但不能校正時給 reason（後端的 uncorrectable_reason）。
 *
 * @param {{ reason?: string | null, error?: unknown }} cause
 */
export function unavailableMessage({ reason, error }) {
  if (error) {
    // 任務 id 格式不對（400）和找不到（404）對使用者是同一件事：網址指的任務不在
    if (error instanceof ApiError && (error.status === 404 || error.status === 400)) return NOT_FOUND;
    return UNREADABLE;
  }
  return REASON_MESSAGES[reason] ?? '這個任務不能校正。';
}
