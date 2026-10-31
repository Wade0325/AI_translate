import { TASK_STATUS } from '../constants/taskStatus';
import { applyFileResult } from './fileResult';
import { connectionRestored } from './connectionLoss';

/**
 * 批次的狀態訊息怎麼改這一批的檔案卡，以及這一批還要不要等伺服器的消息（#286）。
 *
 * 送出批次的連線與接回批次的連線（hooks/useUploadQueue.js）收到的訊息是同一種：批次層級的（沒有
 * file_uid）套在這一批每張還在等的檔案卡上，檔案層級的只套在那個檔案上。接回的連線先收到批次現在的
 * 狀態（backend/app/api/batch.py 的 batch_state），之後的廣播和送出的連線一樣。
 */

/**
 * 一則批次的狀態訊息要怎麼改一張還在等的檔案卡：回傳 (file) => 下一個 state；這則訊息不改檔案卡時是
 * null。呼叫端只套在這一批還在等的檔案卡上（這次送出的、還在處理中的）。收到伺服器的消息就代表又接上了，
 * 連線中斷的記號一律清掉。
 *
 *   - 送出給供應商了（BATCH_SUBMITTED）：改成批次等待，結果到任務頁取回
 *   - 檔案層級的：只改那個檔案，照它的狀態（完成、失敗等，見 fileResult.js）
 *   - 批次層級的失敗：整批沒有送出，這一批每張都標成失敗
 *   - 批次層級的進度：狀態文字改成它
 *   - 批次結束（BATCH_COMPLETED）：每個檔案的結果已經各自送過了，不改
 */
export function batchCardChange(data) {
  if (data.status_code === TASK_STATUS.BATCH_COMPLETED) return null;
  if (data.status_code === TASK_STATUS.BATCH_SUBMITTED) {
    return (file) => ({ ...connectionRestored(file), status: 'batch_pending', statusText: data.status_text });
  }
  if (data.file_uid) {
    return (file) => (file.uid === data.file_uid ? applyFileResult(file, data) : file);
  }
  if (data.status_code === TASK_STATUS.FAILED) {
    return (file) => applyFileResult(file, data);
  }
  return (file) => ({ ...connectionRestored(file), statusText: data.status_text });
}

/** 檔案自己結束的狀態：收到之後就不必再等這個檔案。 */
const FILE_ENDED = new Set([TASK_STATUS.COMPLETED, TASK_STATUS.FAILED, TASK_STATUS.CANCELLED]);

/**
 * 記下這一批還有沒有檔案在等伺服器的消息（uids 是這一批送出的檔案）：送出給供應商之前、還沒結束的
 * 檔案。送出的連線斷了而還有檔案在等，才要接回這一批；接回之後沒有檔案在等了，就不必再連著。
 *
 * 回傳 { heard(data), waiting }：每收到一則訊息呼叫 heard；waiting 是還有沒有檔案在等。
 */
export function batchWatch(uids) {
  const pending = new Set(uids);
  let submitted = false;
  return {
    heard(data) {
      if (data.status_code === TASK_STATUS.BATCH_SUBMITTED) {
        submitted = true;
      } else if (data.file_uid) {
        if (FILE_ENDED.has(data.status_code)) pending.delete(data.file_uid);
      } else if (data.status_code === TASK_STATUS.FAILED) {
        // 整批沒有送出：這一批每個檔案都結束了
        pending.clear();
      }
    },
    get waiting() {
      return !submitted && pending.size > 0;
    },
  };
}
