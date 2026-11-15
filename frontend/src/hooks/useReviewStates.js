import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { message } from 'antd';
import { api } from '../services/api';
import { saveFailureMessage } from '../utils/segmentCorrections';
import { VERIFIED, bulkUndoMessage, reviewToggle } from '../utils/reviewStates';

/** 「其餘全部標成已確認」做完之後，「復原」顯示幾毫秒：一次標了很多個片段，比存一次校正的「復原」留久一點。 */
const BULK_UNDO_SHOWN_MS = 10000;

/**
 * 校正頁標確認狀態（#349）：標一個片段（V、F 與每一列的按鈕）、其餘全部標成已確認，以及它的復原。
 *
 * 確認狀態不是校正，不留校正紀錄，也不進「已存檔，復原」。標一個片段用改一個片段的 PATCH（只帶 review_state），
 * 其餘全部標成已確認與它的復原用一次改很多個片段的端點，在同一個交易裡做完。
 *
 * 送出的順序就是後端存的順序，畫面和後端才不會對不起來：
 *
 * - 標一個片段時畫面先換，再送出：一路按 V、F 時，下一次按的「再按一次是取消」看的是剛標的狀態，不必等上一次存完。
 *   同一個片段的請求一個接一個送；存不進去時改回後端最後存好的狀態，並寫出原因。
 * - 一次改很多個片段時，先等還在送的標記送完再送；它還在送時標的片段排在它後面送，它的結果也不蓋掉這些片段。
 *   它等後端做完才換畫面（先問過一次，標了幾個以後端的結果為準）。
 *
 * @param {string} taskUuid
 * @param {(segKeys: string[], state: string | null) => void} setReviewStates 換掉列表裡的確認狀態（useSegmentCorrections）
 */
export function useReviewStates(taskUuid, setReviewStates) {
  /** 剛做完的「其餘全部標成已確認」那一次標的片段，「復原」用。 */
  const [lastBulk, setLastBulk] = useState(/** @type {string[] | null} */ (null));
  const [bulkPending, setBulkPending] = useState(false);

  const latest = useRef(lastBulk);
  useLayoutEffect(() => {
    latest.current = lastBulk;
  });

  /**
   * 還有標記在送的片段：最後一個請求送完的時候（done）、最後一個請求的編號（存不進去時只有最後一個才改回去），
   * 以及後端最後存好的狀態（saved，改回去用）。都送完了就拿掉，下次標的時候畫面上的狀態就是後端的。
   *
   * @type {import('react').RefObject<Map<string, { done: Promise<void>, id: number, saved: string | null }>>}
   */
  const inFlight = useRef(new Map());
  const nextId = useRef(0);
  /** 一次改很多個片段的請求送完的時候：這段時間標的片段排在它後面送。 */
  const bulkDone = useRef(/** @type {Promise<unknown>} */ (Promise.resolve()));
  /** 一次改很多個片段的請求還在送時標了的片段：它的結果不蓋掉這些片段。 */
  const markedDuringBulk = useRef(/** @type {Set<string> | null} */ (null));

  useEffect(() => {
    if (!lastBulk) return undefined;
    const timer = setTimeout(() => setLastBulk(null), BULK_UNDO_SHOWN_MS);
    return () => clearTimeout(timer);
  }, [lastBulk]);

  const actions = useMemo(() => {
    /** 把一個片段的確認狀態從 previous（畫面上現在的）改成 reviewState。 */
    const mark = (segKey, reviewState, previous) => {
      setReviewStates([segKey], reviewState);
      markedDuringBulk.current?.add(segKey);
      let entry = inFlight.current.get(segKey);
      if (!entry) {
        entry = { done: Promise.resolve(), id: 0, saved: previous };
        inFlight.current.set(segKey, entry);
      }
      const current = entry;
      nextId.current += 1;
      const id = nextId.current;
      current.id = id;
      current.done = Promise.all([current.done, bulkDone.current])
        .then(() => api.transcripts.correctSegment(taskUuid, segKey, { review_state: reviewState }))
        .then(() => {
          current.saved = reviewState;
        }, (error) => {
          if (current.id === id) setReviewStates([segKey], current.saved);
          message.error(`沒有標上確認狀態：${saveFailureMessage(error)}`);
        })
        .finally(() => {
          if (current.id === id) inFlight.current.delete(segKey);
        });
    };

    /**
     * 一次改很多個片段的確認狀態：等還在送的標記送完再送，送的時候標了的片段排在後面。回傳後端的結果，以及畫面
     * 要換的片段（後端改到的，扣掉送的時候又標了的）。
     */
    const changeMany = async (change) => {
      const before = Promise.all([...inFlight.current.values()].map((entry) => entry.done));
      const marked = new Set();
      markedDuringBulk.current = marked;
      const request = before.then(() => api.transcripts.changeReviewStates(taskUuid, change));
      bulkDone.current = request.catch(() => {});
      try {
        const result = await request;
        return { result, apply: result.seg_keys.filter((segKey) => !marked.has(segKey)) };
      } finally {
        if (markedDuringBulk.current === marked) markedDuringBulk.current = null;
      }
    };

    return {
      /**
       * 按了 V（標成已確認）或 F（標成待查），或一列上的同一個按鈕：已經是那個狀態時清掉，其他時候標上去
       * （reviewToggle）。回傳要不要換到下一個片段（V、F 才換，按鈕不換）。
       *
       * @param {import('../utils/reviewStates').ReviewedSegment} segment
       * @param {import('../utils/reviewStates').ReviewState} pressed
       */
      toggle(segment, pressed) {
        const { reviewState, advance } = reviewToggle(segment, pressed);
        mark(segment.seg_key, reviewState, segment.review_state ?? null);
        return advance;
      },

      /** 其餘全部標成已確認：還沒有確認狀態的片段全部標成已確認，待查的不動。做完出現「復原」。 */
      async markRestVerified() {
        setBulkPending(true);
        try {
          const { result, apply } = await changeMany({ reviewState: VERIFIED, onlyIf: null });
          setReviewStates(apply, VERIFIED);
          if (result.changed) setLastBulk(result.seg_keys);
          else message.info('沒有還沒標確認狀態的片段');
        } catch (error) {
          message.error(`沒有標成已確認：${saveFailureMessage(error)}`);
        } finally {
          setBulkPending(false);
        }
      },

      /** 復原剛才的「其餘全部標成已確認」：只清掉那一次標的片段；在這之間被改成待查的不動。 */
      async undoMarkRestVerified() {
        const segKeys = latest.current;
        if (!segKeys) return;
        setLastBulk(null);
        try {
          const { result, apply } = await changeMany({ reviewState: null, onlyIf: VERIFIED, segKeys });
          setReviewStates(apply, null);
          const { type, content } = bulkUndoMessage(result, segKeys.length);
          message[type](content);
        } catch (error) {
          message.error(`沒有復原：${saveFailureMessage(error)}`);
        }
      },
    };
  }, [taskUuid, setReviewStates]);

  return { lastBulk, bulkPending, actions };
}
