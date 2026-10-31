// @ts-nocheck
import { useCallback, useEffect, useRef } from 'react';
import { message } from 'antd';
import { api, WS_URLS } from '../services/api';
import { registerTranscribeSession } from '../utils/transcribeSessions';
import { randomId } from '../utils/id';
import { buildBatchPayload, buildSinglePayload } from '../utils/transcribeRequest';
import { applyFileResult } from '../utils/fileResult';
import { uploadFailure } from '../utils/failure';
import { CONNECTION, connectionLost } from '../utils/connectionLoss';
import { batchCardChange, batchWatch } from '../utils/batchStatus';
import { TASK_STATUS } from '../constants/taskStatus';

/**
 * 封裝「上傳檔案 → 開啟 WebSocket → 接收後端推送」的完整流程。
 *
 * 接收：
 *   - fileList / setFileList：呼叫端維護的 React state
 *   - socketManager：來自 useTranscriptionSocket()
 *
 * 回傳兩個高階函式：
 *   - startRegular({ provider, model, defaults, supports }):
 *       每個檔案各自一條 WS；單檔轉錄／Flex／Standard 模式
 *   - startBatch({ provider, model, defaults, supports }):
 *       所有檔案共用一條 batch WS（Gemini Batch API，50% 折扣）
 *
 * 請求不帶 API 金鑰與提示詞範本：後端從資料庫取用，明文金鑰不經過瀏覽器。
 * 請求的內容（defaults、supports 怎麼用，每個檔案帶哪個補充說明）見 utils/transcribeRequest.js。
 *
 * 單檔任務送出之後連線才斷（伺服器回過排隊中之後）：任務照樣在伺服器上跑。檔案卡寫出連線中斷
 * （utils/connectionLoss.js），一直重新連線、接回這個任務（WS_URLS.reattach），直到收到它結束的狀態，
 * 或檔案卡不再等它（移除、清除）。
 *
 * 批次送出之後、送出給供應商之前連線斷了（#286）：批次可能還在伺服器上跑，也可能根本沒送到。batch_id 是
 * 這裡自己產生的，所以不論伺服器回過什麼，都用它接回這一批（WS_URLS.batchReattach），由伺服器說這一批
 * 現在怎樣（還在送出、排隊、上傳，已經送出給供應商、結束了，或沒有這個批次）。檔案卡和單檔任務一樣寫出
 * 連線中斷，一直重新連線，直到這一批沒有檔案在等了（utils/batchStatus.js）或檔案卡不再等它。
 */

/** 伺服器還沒回任何一則訊息就關掉了單檔任務的連線：任務沒有送出（見 openTranscriptionSocket）。 */
const SUBMISSION_LOST = {
  status_code: TASK_STATUS.FAILED,
  status_text: '提交任務失敗：伺服器還沒回應，連線就中斷了。請重新轉錄',
  error_code: 'SUBMIT_FAILED',
  error_message: '伺服器還沒回應，連線就中斷了',
};

/** 任務結束的狀態：收到之後連線再斷，也不必接回。 */
const ENDED = new Set([TASK_STATUS.COMPLETED, TASK_STATUS.FAILED, TASK_STATUS.CANCELLED]);

/** 一則狀態訊息；不是 JSON 時是 null。 */
function parseStatus(event) {
  try {
    return JSON.parse(event.data);
  } catch {
    return null;
  }
}

/** 還在等這次送出（sessionId）的任務的檔案卡：uids 是這次送出的檔案，而且還在處理中。 */
const isAwaiting = (f, uids, sessionId) =>
  uids.includes(f.uid) && f.sessionId === sessionId && f.status === 'processing';

const isRestartable = (f) =>
  (f.status === 'waiting' || f.status === 'error' || f.status === 'cancelled') &&
  !!f.originFileObj;

export function useUploadQueue({ fileList, setFileList, socketManager, onBatchSubmitted }) {
  // 接回任務的連線斷了時，要知道檔案卡還在不在等這個任務；只在連線的事件裡讀
  const fileListRef = useRef(fileList);
  useEffect(() => {
    fileListRef.current = fileList;
  }, [fileList]);

  const updateFile = useCallback((uid, patch) => {
    setFileList((current) =>
      current.map((f) => (f.uid === uid ? { ...f, ...patch } : f))
    );
  }, [setFileList]);

  const handleSingleStatus = useCallback((data) => {
    setFileList((current) =>
      current.map((f) => (f.uid === data.file_uid ? applyFileResult(f, data) : f))
    );
  }, [setFileList]);

  // 只改還在等這次送出（sessionId）的任務的檔案卡（uids 是這次送出的檔案）：處理中、也還是同一次送出。
  // 已經結束、重新轉錄或移除的檔案卡不動
  const updateAwaiting = useCallback((uids, sessionId, change) => {
    setFileList((current) =>
      current.map((f) => (isAwaiting(f, uids, sessionId) ? change(f) : f))
    );
  }, [setFileList]);

  // 還有沒有檔案卡在等這次送出的任務；只在連線的事件裡讀
  const stillAwaiting = useCallback(
    (uids, sessionId) => fileListRef.current.some((f) => isAwaiting(f, uids, sessionId)),
    []
  );

  // 任務送出之後連線才斷：任務照樣在伺服器上跑，重新連上伺服器、接回它（#280）。伺服器連上就先回
  // 任務現在的狀態（還在排隊或處理中、已經結束，或伺服器上已經沒有這個任務），之後照樣送進度與結果。
  // 連不上（伺服器一則都沒回就斷了）時照指數 backoff 一直再連，直到收到任務結束的狀態、檔案卡不再
  // 等它，或這一端關掉連線（清除全部、重新送出同一個檔案）
  const reattach = useCallback((uid, sessionId, taskUuid) => {
    updateAwaiting([uid], sessionId, (f) => connectionLost(f, CONNECTION.LOST));
    let answered = false;
    socketManager.openSocket(uid, WS_URLS.reattach(uid, taskUuid), {
      autoReconnect: true,
      maxReconnectAttempts: Infinity,
      onMessage: (event) => {
        const data = parseStatus(event);
        if (!data?.file_uid) return;
        answered = true;
        updateAwaiting([uid], sessionId, (f) => applyFileResult(f, data));
        if (ENDED.has(data.status_code)) socketManager.closeSocket(uid);
      },
      onClose: (event, { byClient }) => {
        if (byClient) return;
        if (!stillAwaiting([uid], sessionId)) {
          // 檔案卡已經移除或不再等這個任務：不再重新連線
          socketManager.closeSocket(uid);
          return;
        }
        // 接上之後又斷了：正在重新連線。一則都沒收到就斷了：連不上伺服器
        const connection = answered ? CONNECTION.LOST : CONNECTION.UNREACHABLE;
        answered = false;
        updateAwaiting([uid], sessionId, (f) => connectionLost(f, connection));
      },
    });
  }, [socketManager, updateAwaiting, stillAwaiting]);

  // 送出給供應商了：結果到任務頁取回（TranscriptionContext 會輪詢這一批），這條連線不必再開著
  const batchSubmitted = useCallback((batchId) => {
    message.success('批次已送出，可繼續其他操作。結果將自動更新或可稍後恢復。');
    onBatchSubmitted?.(batchId);
    socketManager.closeSocket(batchId, 1000);
  }, [socketManager, onBatchSubmitted]);

  // 批次的一則狀態訊息（送出的連線與接回的連線共用）：改這一批還在等的檔案卡（utils/batchStatus.js）
  const handleBatchStatus = useCallback((batchId, uids, sessionId, data) => {
    const change = batchCardChange(data);
    if (change) updateAwaiting(uids, sessionId, change);
    if (data.status_code === TASK_STATUS.BATCH_SUBMITTED) batchSubmitted(batchId);
  }, [updateAwaiting, batchSubmitted]);

  // 批次送出之後、送出給供應商之前連線斷了：用 batch_id 接回這一批（#286）。伺服器連上就先回這一批現在
  // 的狀態，之後照樣送進度與結果。連不上時照指數 backoff 一直再連，直到這一批沒有檔案在等了（watch，見
  // utils/batchStatus.js）、檔案卡不再等它，或這一端關掉連線
  const reattachBatch = useCallback((batchId, uids, sessionId, watch) => {
    updateAwaiting(uids, sessionId, (f) => connectionLost(f, CONNECTION.LOST));
    let answered = false;
    socketManager.openSocket(batchId, WS_URLS.batchReattach(batchId), {
      autoReconnect: true,
      maxReconnectAttempts: Infinity,
      onMessage: (event) => {
        const data = parseStatus(event);
        if (!data) return;
        answered = true;
        watch.heard(data);
        handleBatchStatus(batchId, uids, sessionId, data);
        if (!watch.waiting) socketManager.closeSocket(batchId);
      },
      onClose: (event, { byClient }) => {
        if (byClient) return;
        if (!watch.waiting || !stillAwaiting(uids, sessionId)) {
          socketManager.closeSocket(batchId);
          return;
        }
        // 接上之後又斷了：正在重新連線。一則都沒收到就斷了：連不上伺服器
        const connection = answered ? CONNECTION.LOST : CONNECTION.UNREACHABLE;
        answered = false;
        updateAwaiting(uids, sessionId, (f) => connectionLost(f, connection));
      },
    });
  }, [socketManager, updateAwaiting, stillAwaiting, handleBatchStatus]);

  // 建立 session 並把候選檔案標記為 processing；記下模式（只有單檔任務能取消）
  const beginSession = useCallback((candidates, transcribeMode) => {
    const sessionId = randomId('session');
    registerTranscribeSession({
      sessionId,
      fileUids: candidates.map((f) => f.uid),
    });

    const candidateUids = new Set(candidates.map((f) => f.uid));
    setFileList((current) =>
      current.map((f) =>
        candidateUids.has(f.uid)
          ? {
              ...f,
              status: 'processing',
              statusText: '正在上傳檔案...',
              // 失敗過的檔案可以直接再送：上一次的失敗原因與連線中斷的記號不能留到這一次
              failure: null,
              connection: null,
              sessionId,
              transcribeMode,
            }
          : f
      )
    );
    return sessionId;
  }, [setFileList]);

  const uploadFile = useCallback(async (file) => {
    const formData = new FormData();
    formData.append('file', file.originFileObj);
    const { filename } = await api.upload(formData);
    return filename;
  }, []);

  // 標準與 Flex 模式：每個 file uid 一條 WebSocket
  const startRegular = useCallback(async ({ provider, model, defaults, supports }) => {
    const candidates = fileList.filter(isRestartable);
    if (candidates.length === 0) {
      return { skipped: true };
    }

    const sessionId = beginSession(candidates, 'single');

    const openTranscriptionSocket = (file, serverFilename) => {
      // 伺服器收到請求後一定先回一則：排隊中（任務派送了，帶著 task_uuid），或失敗（沒有派送）。之後的
      // 進度與結果都由訊息帶來；一則都還沒收到連線就被伺服器關了，任務就沒有送出
      let opened = false;
      let answered = false;
      let taskUuid = null;
      let ended = false;
      socketManager.openSocket(file.uid, WS_URLS.transcription(file.uid), {
        onOpen: () => {
          opened = true;
          const payload = buildSinglePayload({
            serverFilename: serverFilename ?? file.name,
            file,
            provider,
            model,
            defaults,
            supports,
            sessionId,
          });
          // sentPrompt：送出的補充說明，已送出的檔案卡照這個顯示
          updateFile(file.uid, {
            statusText: '連線成功，正在提交任務...',
            serverFilename,
            sentPrompt: payload.prompt,
          });
          socketManager.sendMessage(file.uid, payload);
        },
        onMessage: (event) => {
          answered = true;
          const data = parseStatus(event);
          if (!data?.file_uid) return;
          taskUuid = data.task_uuid ?? taskUuid;
          ended = ended || ENDED.has(data.status_code);
          handleSingleStatus(data);
        },
        onClose: (event, { byClient }) => {
          if (byClient) return;
          if (!answered) {
            setFileList((current) =>
              current.map((f) =>
                f.uid === file.uid && f.status === 'processing' ? applyFileResult(f, SUBMISSION_LOST) : f
              )
            );
            return;
          }
          // 任務已經派送、還沒結束時連線才斷：接回它
          if (taskUuid && !ended) reattach(file.uid, sessionId, taskUuid);
        },
        onError: () => {
          // 連上之後才出錯：接著一定會關閉，交給 onClose（任務可能已經送出，要接回）。Chromium 在連上之後
          // 斷線時不觸發 error，其他瀏覽器可能會
          if (opened) return;
          message.error(`檔案 ${file.name} 的連線發生錯誤。`);
          updateFile(file.uid, {
            status: 'error',
            percent: 100,
            error: '連線錯誤',
            statusText: '連線失敗',
          });
        },
      });
    };

    // 先 upload 拿到伺服器檔名再開 WS
    for (const file of candidates) {
      try {
        const serverFilename = await uploadFile(file);
        openTranscriptionSocket(file, serverFilename);
      } catch (error) {
        console.error(`上傳檔案 ${file.name} 失敗:`, error);
        updateFile(file.uid, {
          status: 'error',
          statusText: '上傳失敗',
          percent: 100,
          failure: uploadFailure(error),
        });
      }
    }

    return { skipped: false };
  }, [fileList, setFileList, updateFile, socketManager, handleSingleStatus, reattach, beginSession, uploadFile]);

  // 批次模式：所有檔案共用一條 batch WebSocket
  const startBatch = useCallback(async ({ provider, model, defaults, supports }) => {
    const candidates = fileList.filter(isRestartable);
    if (candidates.length === 0) {
      return { skipped: true, reason: 'no-files' };
    }

    const sessionId = beginSession(candidates, 'batch');

    const uploaded = [];
    for (const file of candidates) {
      try {
        const serverFilename = await uploadFile(file);
        uploaded.push({ ...file, serverFilename });
        updateFile(file.uid, {
          statusText: '檔案已上傳，等待批次處理...',
          serverFilename,
        });
      } catch (error) {
        console.error(`上傳檔案 ${file.name} 失敗:`, error);
        updateFile(file.uid, {
          status: 'error',
          statusText: '上傳失敗',
          percent: 100,
          failure: uploadFailure(error),
        });
      }
    }

    if (uploaded.length === 0) {
      message.error('所有檔案上傳失敗，無法送出批次');
      return { skipped: true, reason: 'all-upload-failed' };
    }

    const batchId = randomId('batch');
    const uids = uploaded.map((f) => f.uid);
    const watch = batchWatch(uids);
    let opened = false;

    socketManager.openSocket(batchId, WS_URLS.batch(batchId), {
      onOpen: () => {
        opened = true;
        const payload = buildBatchPayload({
          files: uploaded,
          provider,
          model,
          defaults,
          supports,
          sessionId,
        });
        // sentPrompt：每個檔案送出的補充說明，已送出的檔案卡照這個顯示
        const sentPrompts = new Map(payload.files.map((f) => [f.file_uid, f.prompt]));
        setFileList((current) =>
          current.map((f) =>
            sentPrompts.has(f.uid)
              ? { ...f, statusText: '批次已送出，等待處理...', sentPrompt: sentPrompts.get(f.uid) }
              : f
          )
        );
        socketManager.sendMessage(batchId, payload);
      },
      onMessage: (event) => {
        const data = parseStatus(event);
        if (!data) return;
        watch.heard(data);
        // 送出給供應商了（BATCH_SUBMITTED）：檔案卡改成批次等待，這一端關掉連線，結果靠任務頁取回
        handleBatchStatus(batchId, uids, sessionId, data);
      },
      onClose: (event, { byClient }) => {
        // 沒連上就關了：請求沒有送出，onError 已經標成失敗
        if (byClient || !opened) return;
        // 送出給供應商之前連線斷了：批次可能還在伺服器上跑，也可能沒送到，接回這一批問伺服器
        if (watch.waiting) reattachBatch(batchId, uids, sessionId, watch);
      },
      onError: () => {
        // 連上之後才出錯：接著一定會關閉，交給 onClose。Chromium 在連上之後斷線時不觸發 error
        if (opened) return;
        message.error('批次連線發生錯誤');
        updateAwaiting(uids, sessionId, (f) => ({
          ...f, status: 'error', percent: 100, error: '批次連線錯誤', statusText: '連線失敗',
        }));
      },
    });

    return { skipped: false, batchId };
  }, [fileList, setFileList, updateFile, socketManager, handleBatchStatus, reattachBatch, updateAwaiting,
    beginSession, uploadFile]);

  return { startRegular, startBatch };
}
