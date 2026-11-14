import { TASK_STATUS } from '../constants/taskStatus';
import { failureOf } from './failure';
import { connectionRestored } from './connectionLoss';

/**
 * 依任務的狀態訊息（WebSocket 廣播的形狀：status_code、status_text、task_uuid，完成時再帶 result，失敗時
 * 再帶錯誤碼與細節 error_code、error_message），算出檔案卡的下一個 state。WebSocket 收到的訊息、按取消時
 * 照任務紀錄補上的結果（utils/cancelOutcome.js）都經過這裡，檔案卡完成、失敗、已取消時的欄位只在這裡寫。
 *
 * 收到任務的狀態就代表又和任務接上了：連線中斷的記號（utils/connectionLoss.js）一律清掉。
 */
export function applyFileResult(file, data) {
  const next = {
    ...connectionRestored(file),
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
    // 這份輸出裡有幾位說話者（整份當成同一位說話者時是 1，沒有任何一行時是 0，結果頁不顯示 0），以及
    // 轉錄前選的人數（'auto' 或 1 到 8；人數做出來之前的任務是 null）：選了 2 到 8 人、結果不同時結果頁
    // 提醒（utils/speakerCount.js 的 speakerCountMismatch）。檔案的 speakerCount 是每檔設定的人數，不能共用名稱
    next.resultSpeakerCount = data.result?.speaker_count;
    next.selectedSpeakerCount = data.result?.selected_speaker_count;
    // 可能掉尾的起點（原音檔的秒數，utils/tailLoss.js）：檔案卡與結果頁照它寫出從哪裡起可能沒有轉錄到；
    // 沒有掉尾時是 null
    next.tailLossFrom = data.result?.tail_loss_from_seconds ?? null;
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
