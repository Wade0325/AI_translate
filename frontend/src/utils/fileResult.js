import { TASK_STATUS } from '../constants/taskStatus';
import { failureOf } from './failure';

/**
 * 依任務的狀態訊息（WebSocket 廣播的形狀：status_code、status_text、task_uuid，完成時再帶 result，失敗時
 * 再帶錯誤碼與細節 error_code、error_message），算出檔案卡的下一個 state。WebSocket 收到的訊息、按取消時
 * 照任務紀錄補上的結果（utils/cancelOutcome.js）都經過這裡，檔案卡完成、失敗、已取消時的欄位只在這裡寫。
 */
export function applyFileResult(file, data) {
  const next = {
    ...file,
    statusText: data.status_text,
    task_uuid: data.task_uuid,
  };
  if (data.status_code === TASK_STATUS.COMPLETED) {
    next.status = 'completed';
    next.percent = 100;
    next.result = data.result?.transcripts;
    next.tokens_used = data.result?.tokens_used;
    next.cost = data.result?.cost;
    // Result 頁顯示用：時長、模型與實際使用的來源語言
    next.audioDurationSec = data.result?.audio_duration_seconds;
    next.model = data.result?.model ?? file.model;
    next.sourceLanguage = data.result?.source_language;
    // 轉錄結果裡實際出現的說話者人數；沒有片段帶說話者編號時是 0，結果頁不顯示
    next.speakerCount = data.result?.speaker_count;
  } else if (data.status_code === TASK_STATUS.FAILED) {
    next.status = 'error';
    next.percent = 100;
    next.error = data.status_text;
    // 錯誤碼與細節：檔案卡照錯誤碼寫出原因與下一步（components/FailureNotice.jsx）。訊息沒帶錯誤碼與
    // 細節時，狀態文字就是原因
    next.failure = data.error_code || data.error_message
      ? failureOf(data)
      : { code: null, detail: data.status_text || '' };
  } else if (data.status_code === TASK_STATUS.CANCELLED) {
    next.status = 'cancelled';
    next.percent = 100;
  }
  return next;
}
