import { TASK_STATUS } from '../constants/taskStatus';

/**
 * 依任務的狀態訊息（WebSocket 廣播的形狀：status_code、status_text、task_uuid，完成時再帶 result），
 * 算出檔案卡的下一個 state。WebSocket 收到的訊息、按取消時照任務紀錄補上的結果（utils/cancelOutcome.js）
 * 都經過這裡，檔案卡完成、失敗、已取消時的欄位只在這裡寫。
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
  } else if (data.status_code === TASK_STATUS.FAILED) {
    next.status = 'error';
    next.percent = 100;
    next.error = data.status_text;
  } else if (data.status_code === TASK_STATUS.CANCELLED) {
    next.status = 'cancelled';
    next.percent = 100;
  }
  return next;
}
