import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import { message } from 'antd';
import { api } from '../services/api';
import { bulkUndoMessage } from '../utils/correctionHistory';
import {
  deleteRequest,
  correctTextRequest,
  isUserDeleted,
  restoreRequest,
  saveFailureMessage,
  savesReducer,
  undoMessage,
} from '../utils/segmentCorrections';

/** 「已存」顯示幾毫秒之後收起來。 */
const SAVED_SHOWN_MS = 3000;
/** 「已存檔，復原」顯示幾毫秒。 */
const UNDO_SHOWN_MS = 6000;

/**
 * 校正頁改文字、刪掉與還原片段（#348）：片段的校正後版本、每個片段的存檔狀態、正在改哪一個片段，以及剛存的
 * 那一次操作（「已存檔，復原」用）。校正的歷程（#355）：讀一個片段的歷程、回到某一版、整批復原。
 *
 * 每一次校正就是一個請求，存檔的結果（後端回的片段新內容）直接換進列表。actions 裡的函式身分不變，片段列表的
 * 每一列可以照常用 memo，只有改到的那幾列重畫。
 *
 * @param {string} taskUuid
 * @param {import('../utils/segmentCorrections').Segment[]} initialSegments GET /transcripts/{task_uuid} 的片段
 */
export function useSegmentCorrections(taskUuid, initialSegments) {
  const [segments, setSegments] = useState(initialSegments);
  const [saves, dispatch] = useReducer(savesReducer, {});
  const [editing, setEditing] = useState(/** @type {import('../utils/segmentCorrections').Editing | null} */ (null));
  const [lastOperation, setLastOperation] = useState(/** @type {string | null} */ (null));

  // 事件處理讀最新的內容：actions 的身分才能不變（每改一次就換一份函式，列表的每一列都得重畫）
  const latest = useRef({ segments, saves, editing, lastOperation });
  useLayoutEffect(() => {
    latest.current = { segments, saves, editing, lastOperation };
  });

  const settleTimers = useRef(/** @type {Map<string, ReturnType<typeof setTimeout>>} */ (new Map()));
  useEffect(() => {
    const timers = settleTimers.current;
    return () => timers.forEach(clearTimeout);
  }, []);

  // 「已存檔，復原」只顯示幾秒
  useEffect(() => {
    if (!lastOperation) return undefined;
    const timer = setTimeout(() => setLastOperation(null), UNDO_SHOWN_MS);
    return () => clearTimeout(timer);
  }, [lastOperation]);

  // 還有存檔中或存檔失敗的片段時，關掉頁面之前先問一次：失敗時打的字只留在這個頁面上
  const unsaved = useMemo(() => Object.values(saves).some((save) => save.status !== 'saved'), [saves]);
  useEffect(() => {
    if (!unsaved) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [unsaved]);

  const actions = useMemo(() => {
    const segmentOf = (segKey) => latest.current.segments.find((s) => s.seg_key === segKey);

    /** 後端回的片段新內容換進列表。 */
    const applySegments = (updated) => {
      if (!updated.length) return;
      const byKey = new Map(updated.map((s) => [s.seg_key, s]));
      setSegments((current) => current.map((s) => byKey.get(s.seg_key) ?? s));
    };

    const clearSettle = (segKey) => {
      clearTimeout(settleTimers.current.get(segKey));
      settleTimers.current.delete(segKey);
    };

    /** 送出一次校正。成功時換上後端回的內容，有記下校正紀錄時出現「已存檔，復原」；失敗時留著送出的內容。 */
    const send = async (segKey, request) => {
      clearSettle(segKey);
      dispatch({ type: 'start', segKey, request });
      // 存檔中不給復原上一次：免得按到的不是畫面上最新的那一次
      setLastOperation(null);
      try {
        const { operation_id: operationId, segment } = await api.transcripts.correctSegment(taskUuid, segKey, request);
        applySegments([segment]);
        dispatch({ type: 'succeed', segKey });
        settleTimers.current.set(segKey, setTimeout(() => dispatch({ type: 'settle', segKey }), SAVED_SHOWN_MS));
        if (operationId) setLastOperation(operationId);
      } catch (error) {
        dispatch({ type: 'fail', segKey, message: saveFailureMessage(error) });
      }
    };

    const saving = (segKey) => latest.current.saves[segKey]?.status === 'saving';

    /**
     * 復原一次操作，換上那次操作改到的片段的新內容，結果照 messageOf 寫在頁面上方。回傳復原端點的回應；
     * 沒有復原（連不上、被擋下）時寫原因，回傳 null。
     */
    const undoOperation = async (operationId, messageOf) => {
      setLastOperation(null);
      try {
        const result = await api.transcripts.undo(taskUuid, operationId);
        applySegments(result.segments);
        // 正在改的片段被復原了：照復原之後的內容，不把改之前打的字存回去
        const editingKey = latest.current.editing?.segKey;
        if (editingKey && result.segments.some((s) => s.seg_key === editingKey)) setEditing(null);
        const { type, content } = messageOf(result);
        message[type](content);
        return result;
      } catch (error) {
        message.error(`沒有復原：${saveFailureMessage(error)}`);
        return null;
      }
    };

    /** 這個片段正在改時，結束改（不存）：在同一列按了刪除、還原或回到原始轉錄，以那個動作為準。 */
    const dropEditing = (segKey) => {
      if (latest.current.editing?.segKey === segKey) setEditing(null);
    };

    return {
      /**
       * 開始改一個片段的文字。selection 是游標（或選取的範圍）在文字裡的位置，沒有時游標放在最後。存檔中與
       * 使用者刪掉的片段不能改：前者等存完，後者先還原。
       */
      startEditing(segKey, selection = null) {
        const segment = segmentOf(segKey);
        if (!segment || saving(segKey) || isUserDeleted(segment)) return;
        setEditing({ segKey, selection });
      },

      /** 按 Enter 或點到別處：有改就存成一次校正；沒改時不送，存檔失敗留著的內容也一起收掉。 */
      finishEditing(segKey, draft) {
        if (latest.current.editing?.segKey !== segKey) return;
        setEditing(null);
        const segment = segmentOf(segKey);
        if (!segment) return;
        const request = correctTextRequest(segment, draft);
        if (request) send(segKey, request);
        else dispatch({ type: 'discard', segKey });
      },

      /** 按 Esc：放棄這次輸入，回到改之前的內容。 */
      cancelEditing: dropEditing,

      /** 刪掉片段（片段上的刪除鈕）。 */
      remove(segKey) {
        if (saving(segKey)) return;
        dropEditing(segKey);
        send(segKey, deleteRequest());
      },

      /** 還原刪掉的片段：送回刪掉之前的文字。 */
      restore(segKey) {
        const segment = segmentOf(segKey);
        if (!segment || saving(segKey)) return;
        send(segKey, restoreRequest(segment));
      },

      /**
       * 回到歷程裡的某一版（#355）：把那一版的內容當成一次普通的校正送出（utils/correctionHistory.js 的
       * historyEntries 算好的 request）。回到原始轉錄是文字與說話者都回去，後端各記一筆、共用一個操作編號。
       */
      returnTo(segKey, request) {
        if (!request || !segmentOf(segKey) || saving(segKey)) return;
        dropEditing(segKey);
        send(segKey, request);
      },

      /** 讀一個片段的校正紀錄（#355 的歷程）：每一筆（舊的在前）與原始轉錄。 */
      correctionRecords(segKey) {
        return api.transcripts.correctionRecords(taskUuid, segKey);
      },

      /**
       * 歷程裡的「整批復原」（#355）：復原一次改很多個片段的操作。之後又改過的片段略過，寫出略過了幾個。
       * 整批復原本身也是一次操作，存完一樣出現「已存檔，復原」。
       */
      async undoBulk(operationId) {
        const result = await undoOperation(operationId, bulkUndoMessage);
        if (result?.operation_id) setLastOperation(result.operation_id);
      },

      /** 重試存檔失敗的那一次。 */
      retry(segKey) {
        const save = latest.current.saves[segKey];
        if (save?.status === 'failed') send(segKey, save.request);
      },

      /** 放棄存檔失敗的內容，回到存好的內容。 */
      discard(segKey) {
        dispatch({ type: 'discard', segKey });
      },

      /** 「已存檔，復原」：收回剛存的那一次。 */
      async undo() {
        const operationId = latest.current.lastOperation;
        if (operationId) await undoOperation(operationId, undoMessage);
      },
    };
  }, [taskUuid]);

  return { segments, saves, editing, lastOperation, actions };
}
