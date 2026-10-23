/**
 * 按取消之後：取消端點（POST /transcription/{file_uid}/cancel）的回應對應到要顯示的提示（antd
 * message.open 的設定 { type, content }），以及檔案卡要改的欄位。不碰 React；後端 API 由呼叫端傳入
 * （services/api.js 的 api），測試換成假的。
 *
 *   { file_uid, cancelled: true }
 *   { file_uid, cancelled: false, reason: 'not-started' | 'finished' }
 *
 * 端點的回應只在這個檔案讀：tests/integration/test_provider_seam.py 對照端點，確認端點回的每一種
 * 原因這裡都認得。沒有取消時，後端用 reason 說明原因（#126），兩種要分開講，使用者才知道要不要
 * 再按一次（#161）：
 *   - not-started：後端查不到任務的登記。多半是任務還沒提交到佇列（可能還在上傳），稍後再按就能
 *     取消；任務結束、登記已經清掉時也是這個原因。
 *   - finished：任務已經結束（完成或失敗），或已經記下結果、正在收尾，來不及取消。
 *
 * 檔案卡停在處理中、任務其實已經結束時（例如 WebSocket 在宣告結果前斷了），兩種原因都可能回，
 * 稍後再按也一樣（#186）。所以沒有取消時先查這次送出的任務紀錄（GET /history/{task_uuid}）：
 * 任務已經完成、失敗或取消，就把檔案卡改成那個結果；查不到或還在處理中，才照原因說。
 */

import { downloadFormats } from '../constants/downloadFormats.js';
import { TASK_STATUS } from '../constants/taskStatus.js';

/**
 * 取消一個處理中的檔案，回傳 { notice, patch }：notice 是要顯示的提示；patch 是檔案卡還在處理中時
 * 要改的欄位，取消了時是 null（檔案卡等後端宣告已取消）。取消請求本身失敗時丟出例外。
 */
export async function cancelFile(file, api) {
  const response = await api.transcription.cancel(file.uid);
  if (response?.cancelled === true) {
    return { notice: { type: 'info', content: `已取消任務：${file.name}` }, patch: null };
  }
  // 不論原因，任務紀錄說任務已經結束，就照紀錄說：使用者才不會照提示一直再按（#186）
  return (await endedTask(file, api))
    ?? { notice: notCancelledNotice(response?.reason), patch: { statusText: '處理中...' } };
}

/**
 * 這次送出的任務如果已經結束，照它的任務紀錄回傳 { notice, patch }；還沒結束或查不到時是 null。
 *
 * 檔案的 task_uuid 來自狀態訊息（useUploadQueue 的 applyFileResult），沒收到過就沒有。紀錄的
 * session_id 要是這次送出的：重新轉錄時檔案上可能還留著上一個任務的 task_uuid，不能拿上一個任務
 * 的結果回答（新的音檔可能還在上傳）。
 */
async function endedTask(file, api) {
  if (!file.task_uuid) return null;
  let record;
  try {
    record = await api.history.get(file.task_uuid);
  } catch {
    // 查不到紀錄（例如已經在 History 頁面刪掉）或連不上：照取消端點的原因說
    return null;
  }
  if (record.session_id !== file.sessionId) return null;
  switch (record.status) {
    case TASK_STATUS.COMPLETED: {
      const result = await transcripts(file.task_uuid, api);
      return {
        notice: { type: 'info', content: `任務已經完成，無法取消：${file.name}` },
        patch: {
          status: 'completed',
          percent: 100,
          // 取不回結果時檔案卡沒有東西可以預覽、下載，請使用者到 History 頁面（和批次完成時一樣）
          statusText: result ? '任務完成' : '任務完成，結果請到 History 頁面下載',
          result,
          tokens_used: record.total_tokens,
          cost: record.cost,
          audioDurationSec: record.audio_duration_seconds,
          model: record.model_used ?? file.model,
          sourceLanguage: record.source_language,
        },
      };
    }
    case TASK_STATUS.FAILED: {
      // 和失敗時的廣播同一個寫法
      const statusText = record.error_message ? `任務失敗: ${record.error_message}` : '任務失敗';
      return {
        notice: { type: 'info', content: `任務已經失敗，無法取消：${file.name}` },
        patch: { status: 'error', percent: 100, statusText, error: statusText },
      };
    }
    case TASK_STATUS.CANCELLED:
      return {
        notice: { type: 'info', content: `任務已經取消：${file.name}` },
        patch: { status: 'cancelled', percent: 100, statusText: '任務已取消' },
      };
    default:
      return null;
  }
}

/**
 * 完成的任務的四種輸出格式，和完成時廣播給畫面的 result.transcripts 一樣：任務紀錄不帶轉錄結果，
 * 一種一種下載。產生不出內容的格式後端回 404，和廣播一樣當成空字串；一種都取不回來時是 null。
 */
async function transcripts(taskUuid, api) {
  const downloads = await Promise.allSettled(
    downloadFormats.map(({ key }) => api.history.downloadTranscript(taskUuid, key)),
  );
  if (downloads.every((d) => d.status === 'rejected')) return null;
  return Object.fromEntries(
    downloadFormats.map(({ key }, i) => [key, downloads[i].status === 'fulfilled' ? downloads[i].value : '']),
  );
}

function notCancelledNotice(reason) {
  switch (reason) {
    case 'not-started':
      return { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' };
    case 'finished':
      return { type: 'info', content: '任務已經結束，無法取消。' };
    default:
      // 認不得的原因不猜是哪一種，也不叫使用者再按：說錯原因正是 #161 要修的問題
      return { type: 'warning', content: '任務沒有取消。' };
  }
}
