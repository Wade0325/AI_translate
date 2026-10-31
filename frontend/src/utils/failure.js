import { ERROR_ACTIONS, ERROR_CODES } from '../constants/errorCodes';

/**
 * 任務為什麼失敗：從失敗的狀態訊息或任務紀錄取出錯誤碼與細節（兩邊的欄位都叫 error_code、
 * error_message，見 backend/app/core/error_codes.py 的 Failure.fields）。
 *
 * 回傳 { code, detail }：code 在這個版本之前失敗的任務紀錄、或後端沒附錯誤碼時是 null；detail 是後端
 * 寫的原始原因，沒有時是空字串。
 */
export function failureOf(data) {
  return { code: data?.error_code || null, detail: data?.error_message || '' };
}

/**
 * 要顯示的失敗內容：{ code, reason, nextStep, action, detail }。
 *
 *   - reason：一句話的原因；nextStep：使用者接下來可以做什麼（文案見 constants/errorCodes.js）
 *   - action：{ label, to } 前往處理的連結，沒有時是 null
 *   - detail：後端寫的原始原因，放在原因下面；和 reason 重複或沒有時是 null
 *
 * 沒有錯誤碼（舊的任務紀錄）時照細節顯示，和以前一樣；認不得的錯誤碼（後端比前端新）時說任務失敗，
 * 錯誤碼與細節照樣顯示，使用者回報時附得上。
 */
export function describeFailure(failure) {
  const code = failure?.code || null;
  const detail = failure?.detail || '';
  const copy = code ? ERROR_CODES[code] : undefined;
  if (!copy) {
    return {
      code,
      reason: code || !detail ? '任務失敗' : detail,
      nextStep: null,
      action: null,
      detail: code && detail ? detail : null,
    };
  }
  return {
    code,
    reason: copy.reason,
    nextStep: copy.nextStep,
    action: copy.action ? ERROR_ACTIONS[copy.action] : null,
    detail: detail || null,
  };
}

/**
 * 上傳失敗：任務還沒送到後端，錯誤碼是前端自己的 UPLOAD_FAILED。伺服器回了原因（例如不支援的格式、
 * 空檔案）時當細節；連不上伺服器時瀏覽器的錯誤訊息（英文、說不出原因）不放。
 */
export function uploadFailure(error) {
  return { code: 'UPLOAD_FAILED', detail: error?.name === 'ApiError' ? error.message || '' : '' };
}
