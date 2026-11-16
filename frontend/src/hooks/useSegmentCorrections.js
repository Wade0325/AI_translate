import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
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
import { nextSpeakerAfter, reassignMessage, renameMessage } from '../utils/speakers';

/** 「已存」顯示幾毫秒之後收起來。 */
const SAVED_SHOWN_MS = 3000;
/** 「已存檔，復原」顯示幾毫秒。 */
const UNDO_SHOWN_MS = 6000;

/** 存完一次校正之後，「復原」旁邊寫的字。 */
const SAVED_LABEL = '已存檔';

/**
 * 剛存的那一次操作：「已存檔，復原」那一格寫的字（label）與復原時送的操作編號（id）。
 *
 * @typedef {{ id: string, label: string }} LastOperation
 */

/**
 * 校正頁改文字、刪掉與還原片段（#348）、改說話者（#354）、全部取代（#356），以及替說話者取名字（#359）：片段的
 * 校正後版本、每個片段的存檔狀態、正在改哪一個片段、新的說話者編號、說話者名稱，以及剛存的那一次操作（「已存檔，
 * 復原」用）。校正的歷程（#355）：讀一個片段的歷程、回到某一版、整批復原。
 *
 * 每一次校正就是一個請求，存檔的結果（後端回的片段新內容）直接換進列表。actions 裡的函式身分不變，片段列表的
 * 每一列可以照常用 memo，只有改到的那幾列重畫。
 *
 * @param {string} taskUuid
 * @param {import('../utils/segmentCorrections').Segment[]} initialSegments GET /transcripts/{task_uuid} 的片段
 * @param {string} [initialNextSpeaker] GET /transcripts/{task_uuid} 的 next_speaker（新的說話者編號）
 * @param {import('../utils/speakers').SpeakerNames} [initialSpeakerNames] GET /transcripts/{task_uuid} 的 speaker_names
 */
export function useSegmentCorrections(taskUuid, initialSegments, initialNextSpeaker = 'S0', initialSpeakerNames = {}) {
  const [segments, setSegments] = useState(initialSegments);
  const [saves, dispatch] = useReducer(savesReducer, {});
  const [editing, setEditing] = useState(/** @type {import('../utils/segmentCorrections').Editing | null} */ (null));
  const [lastOperation, setLastOperation] = useState(/** @type {LastOperation | null} */ (null));
  const [nextSpeaker, setNextSpeaker] = useState(() => nextSpeakerAfter(initialNextSpeaker, initialSegments));
  const [speakerNames, setSpeakerNames] = useState(initialSpeakerNames);

  // 事件處理讀最新的內容：actions 的身分才能不變（每改一次就換一份函式，列表的每一列都得重畫）
  const latest = useRef({ segments, saves, editing, lastOperation, speakerNames });
  useLayoutEffect(() => {
    latest.current = { segments, saves, editing, lastOperation, speakerNames };
  });

  const settleTimers = useRef(/** @type {Map<string, ReturnType<typeof setTimeout>>} */ (new Map()));
  // 還沒有回應的校正：全部取代等它們存完才送，伺服器取代的才是畫面上最新的內容，晚到的回應也不會蓋掉取代的結果
  const inflight = useRef(/** @type {Set<Promise<unknown>>} */ (new Set()));
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

    /**
     * 後端回的片段新內容換進列表；指定了新的說話者時，新的說話者編號接著往上加。確認狀態留著畫面上的：它只由
     * useReviewStates 換（#349），標了還在送的時候存好一次校正，回應裡的確認狀態可能是標之前的。
     */
    const applySegments = (updated) => {
      if (!updated.length) return;
      const byKey = new Map(updated.map((s) => [s.seg_key, s]));
      setSegments((current) => current.map((s) => {
        const next = byKey.get(s.seg_key);
        return next ? { ...next, review_state: s.review_state } : s;
      }));
      setNextSpeaker((next) => nextSpeakerAfter(next, updated));
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
      const pending = api.transcripts.correctSegment(taskUuid, segKey, request);
      inflight.current.add(pending);
      try {
        const { operation_id: operationId, segment } = await pending;
        applySegments([segment]);
        dispatch({ type: 'succeed', segKey });
        settleTimers.current.set(segKey, setTimeout(() => dispatch({ type: 'settle', segKey }), SAVED_SHOWN_MS));
        if (operationId) setLastOperation({ id: operationId, label: SAVED_LABEL });
      } catch (error) {
        dispatch({ type: 'fail', segKey, message: saveFailureMessage(error) });
      } finally {
        inflight.current.delete(pending);
      }
    };

    /** 復原或全部取代改到正在改的片段時，照伺服器回的內容，不把改之前打的字存回去。 */
    const dropEditingIn = (updated) => {
      const editingKey = latest.current.editing?.segKey;
      if (editingKey && updated.some((s) => s.seg_key === editingKey)) setEditing(null);
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
        dropEditingIn(result.segments);
        // 復原的是取名字時，名稱跟著回去（#359）
        if (result.speaker_names) setSpeakerNames(result.speaker_names);
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

      /**
       * 改一個片段的說話者（#354）：換成現有的另一位，或新的說話者（新的說話者編號）。和改文字一樣是一次校正，
       * 有自己的存檔狀態，存完出現「已存檔，復原」。存檔中與使用者刪掉的片段不能改。
       */
      setSpeaker(segKey, speaker) {
        const segment = segmentOf(segKey);
        if (!segment || saving(segKey) || isUserDeleted(segment)) return;
        if ((segment.speaker ?? null) === speaker) return;
        send(segKey, { speaker });
      },

      /**
       * 把這位說話者全部換成另一位（#354）：fromSpeaker 是 null 時換的是沒有說話者的片段。一次操作，做完出現
       * 「已把 N 個片段換成 Sx，復原」，按下去整批收回。
       */
      async reassignSpeaker(fromSpeaker, toSpeaker) {
        // 和全部取代一樣，先等還沒存完的校正：免得晚到的回應蓋掉換過的說話者
        await Promise.allSettled([...inflight.current]);
        setLastOperation(null);
        try {
          const result = await api.transcripts.reassignSpeaker(taskUuid, fromSpeaker, toSpeaker);
          applySegments(result.segments);
          if (result.operation_id) {
            setLastOperation({
              id: result.operation_id,
              label: reassignMessage(result.changed, toSpeaker, latest.current.speakerNames),
            });
          } else {
            message.info('沒有要換的片段');
          }
        } catch (error) {
          message.error(`沒有換：${saveFailureMessage(error)}`);
        }
      },

      /**
       * 替說話者取名字（#359）：name 是空的時清掉，回到顯示說話者編號。一次校正，存完出現「已把 S0 叫做「王小明」，
       * 復原」，這位說話者的所有片段一起換成新名稱。回 null 表示存好了（或名稱沒變）；沒存時回寫給使用者看的原因，
       * 例如另一位說話者已經用了這個名稱，取名字的輸入框把它寫出來。
       *
       * @param {string} speaker 說話者編號
       * @param {string} name
       * @returns {Promise<string | null>}
       */
      async renameSpeaker(speaker, name) {
        setLastOperation(null);
        try {
          const result = await api.transcripts.setSpeakerName(taskUuid, speaker, name);
          setSpeakerNames(result.speaker_names);
          if (result.operation_id) {
            setLastOperation({ id: result.operation_id, label: renameMessage(speaker, result.name) });
          }
          return null;
        } catch (error) {
          return saveFailureMessage(error);
        }
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
        if (result?.operation_id) setLastOperation({ id: result.operation_id, label: SAVED_LABEL });
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

      /** 收起「已存檔，復原」，不復原（例如切換整份當成同一位說話者之後）。 */
      dismissUndo() {
        setLastOperation(null);
      },

      /**
       * 全部取代（#356）：伺服器在同一個交易裡改完，算一次操作，做完出現「復原」可以整批收回。還沒存完的校正先等它們
       * 存完。回伺服器的結果（實際改到的片段數與處數）；沒有取代成功時回 null，並寫出原因。
       *
       * @param {string} find
       * @param {string} replacement
       */
      async replaceAll(find, replacement) {
        await Promise.allSettled([...inflight.current]);
        setLastOperation(null);
        try {
          const result = await api.transcripts.replaceAll(taskUuid, find, replacement);
          applySegments(result.segments);
          dropEditingIn(result.segments);
          if (result.operation_id) {
            setLastOperation({
              id: result.operation_id,
              label: `已取代 ${result.changed_segments} 個片段，一共 ${result.occurrences} 處`,
            });
          } else {
            message.info('沒有片段需要改');
          }
          return result;
        } catch (error) {
          message.error(`沒有取代：${saveFailureMessage(error)}`);
          return null;
        }
      },

      /** 「已存檔，復原」：收回剛存的那一次（全部取代是整批收回）。 */
      async undo() {
        const operation = latest.current.lastOperation;
        if (operation) await undoOperation(operation.id, undoMessage);
      },
    };
  }, [taskUuid]);

  /**
   * 這些片段的確認狀態換成 state（#349 的 useReviewStates 用：標一個片段時先換再送，整批標等後端做完才換）。確認狀態不是校正，不動存檔狀態
   * 與「已存檔，復原」；只換確認狀態，不換整個片段，同時在存的文字才不會被蓋掉。
   */
  const setReviewStates = useCallback((segKeys, state) => {
    const keys = new Set(segKeys);
    if (!keys.size) return;
    setSegments((current) => current.map((s) => (
      keys.has(s.seg_key) && (s.review_state ?? null) !== state ? { ...s, review_state: state } : s
    )));
  }, []);

  return { segments, saves, editing, lastOperation, nextSpeaker, speakerNames, actions, setReviewStates };
}
