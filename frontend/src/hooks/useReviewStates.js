import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { message } from 'antd';
import { api } from '../services/api';
import { saveFailureMessage } from '../utils/segmentCorrections';
import { VERIFIED, bulkUndoMessage } from '../utils/reviewStates';

/** 「其餘全部標成已確認」做完之後，「復原」顯示幾毫秒：一次標了很多個片段，比存一次校正的「復原」留久一點。 */
const BULK_UNDO_SHOWN_MS = 10000;

/**
 * 校正頁標確認狀態（#349）：標一個片段、其餘全部標成已確認，以及它的復原。
 *
 * 確認狀態不是校正，不留校正紀錄，也不進「已存檔，復原」。標一個片段用改一個片段的 PATCH（只帶 review_state），
 * 其餘全部標成已確認與它的復原用一次改很多個片段的端點，在同一個交易裡做完。
 *
 * 標一個片段時畫面先換，再送出：一路按 V、F 時，下一次按的「再按一次是取消」看的是剛標的狀態，不必等上一次存完。
 * 同一個片段的請求一個接一個送，後端存的順序和按的順序相同；存不進去時改回去並寫出原因。其餘全部標成已確認
 * 等後端做完才換（它先問過一次，標了幾個以後端的結果為準），送出之前先等還在送的標記送完。
 *
 * @param {string} taskUuid
 * @param {(segKeys: string[], state: string | null) => void} setReviewStates 換掉列表裡的確認狀態（useSegmentCorrections）
 */
export function useReviewStates(taskUuid, setReviewStates) {
  /** 剛做完的「其餘全部標成已確認」：那一次標的片段，「復原」用。 */
  const [lastBulk, setLastBulk] = useState(/** @type {{ segKeys: string[], count: number } | null} */ (null));
  const [bulkPending, setBulkPending] = useState(false);

  const latest = useRef(lastBulk);
  useLayoutEffect(() => {
    latest.current = lastBulk;
  });

  /** 每個片段最後一次標的請求（排在前一次後面）與它的編號：存不進去時，只有最後一次才改回去。 */
  const queues = useRef(/** @type {Map<string, { done: Promise<unknown>, id: number }>} */ (new Map()));
  const nextId = useRef(0);

  useEffect(() => {
    if (!lastBulk) return undefined;
    const timer = setTimeout(() => setLastBulk(null), BULK_UNDO_SHOWN_MS);
    return () => clearTimeout(timer);
  }, [lastBulk]);

  /** 等每個片段還在送的標記都送完：一次改很多個片段時，後端看到的才是畫面上已經換好的確認狀態。 */
  const settled = () => Promise.all([...queues.current.values()].map((queue) => queue.done));

  const actions = useMemo(() => ({
    /**
     * 把一個片段的確認狀態從 previous 改成 reviewState（null 是清掉）。V、F 的「再按一次是取消」由呼叫的人決定
     * （reviewStates.js 的 reviewToggle）。
     *
     * @param {string} segKey
     * @param {string | null} reviewState
     * @param {string | null} previous 片段現在的確認狀態：存不進去時改回它
     */
    mark(segKey, reviewState, previous) {
      setReviewStates([segKey], reviewState);
      nextId.current += 1;
      const id = nextId.current;
      const send = () => api.transcripts.correctSegment(taskUuid, segKey, { review_state: reviewState });
      const before = queues.current.get(segKey)?.done ?? Promise.resolve();
      const done = before.then(send).catch((error) => {
        if (queues.current.get(segKey)?.id === id) setReviewStates([segKey], previous);
        message.error(`沒有標上確認狀態：${saveFailureMessage(error)}`);
      });
      queues.current.set(segKey, { done, id });
    },

    /** 其餘全部標成已確認：還沒有確認狀態的片段全部標成已確認，待查的不動。做完出現「復原」。 */
    async markRestVerified() {
      setBulkPending(true);
      try {
        await settled();
        const result = await api.transcripts.changeReviewStates(taskUuid, { reviewState: VERIFIED, onlyIf: null });
        setReviewStates(result.seg_keys, VERIFIED);
        if (result.changed) setLastBulk({ segKeys: result.seg_keys, count: result.changed });
        else message.info('沒有還沒標確認狀態的片段');
      } catch (error) {
        message.error(`沒有標成已確認：${saveFailureMessage(error)}`);
      } finally {
        setBulkPending(false);
      }
    },

    /** 復原剛才的「其餘全部標成已確認」：只清掉那一次標的片段；在這之間被改成待查的不動。 */
    async undoMarkRestVerified() {
      const bulk = latest.current;
      if (!bulk) return;
      setLastBulk(null);
      try {
        await settled();
        const result = await api.transcripts.changeReviewStates(
          taskUuid, { reviewState: null, onlyIf: VERIFIED, segKeys: bulk.segKeys },
        );
        setReviewStates(result.seg_keys, null);
        const { type, content } = bulkUndoMessage(result, bulk.count);
        message[type](content);
      } catch (error) {
        message.error(`沒有復原：${saveFailureMessage(error)}`);
      }
    },
  }), [taskUuid, setReviewStates]);

  return { lastBulk, bulkPending, actions };
}
