import { useCallback, useEffect, useRef } from 'react';

/**
 * 集中管理轉錄相關 WebSocket 連線：
 *  - 自動清理：hook 卸載時所有 socket 都會關閉
 *  - 心跳：每 30s 送一次 ping，避免代理層因閒置而中斷連線
 *  - 重連：非正常斷線 (close code !== 1000) 時依指數 backoff 重連，最多 N 次
 *
 * 設計成低階 API，呼叫者透過 ``openSocket(id, url, handlers)`` 啟動連線，並收到
 * 事件 callback；同一個 ``id`` 第二次呼叫時舊連線會先被關閉。
 */

const HEARTBEAT_INTERVAL_MS = 30_000;
const RECONNECT_MAX_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 30_000;

export function useTranscriptionSocket() {
  // { [id]: { socket, attempts, hbTimer, reconnectTimer, opts } }
  const slotsRef = useRef({});

  const _clearTimers = (slot) => {
    if (slot.hbTimer) {
      clearInterval(slot.hbTimer);
      slot.hbTimer = null;
    }
    if (slot.reconnectTimer) {
      clearTimeout(slot.reconnectTimer);
      slot.reconnectTimer = null;
    }
  };

  const closeSocket = useCallback((id, code = 1000) => {
    const slot = slotsRef.current[id];
    if (!slot) return;
    delete slotsRef.current[id];
    _clearTimers(slot);
    try {
      slot.socket.close(code);
    } catch {
      /* ignore */
    }
  }, []);

  const closeAll = useCallback((code = 1000) => {
    Object.keys(slotsRef.current).forEach((id) => closeSocket(id, code));
  }, [closeSocket]);

  /**
   * 建立 / 重新建立一條 WebSocket 連線。
   *
   * @param {string} id    任務識別碼（單檔轉錄為 file uid，批次為 batchId）
   * @param {string} url   WebSocket URL
   * @param {object} handlers
   *   - onOpen(event, socket): 連線成功（可在此送出 payload）
   *   - onMessage(event):       收到伺服器訊息
   *   - onError(event):         連線錯誤
   *   - onClose(event):         連線關閉（不論正常或異常）
   *   - autoReconnect:          非正常關閉時是否自動重連，預設 false
   */
  const openSocket = useCallback((id, url, handlers = {}) => {
    const {
      onOpen,
      onMessage,
      onError,
      onClose,
      autoReconnect = false,
    } = handlers;

    // 同 id 重複呼叫 → 先關閉舊連線
    if (slotsRef.current[id]) {
      closeSocket(id);
    }

    const slot = {
      socket: null,
      attempts: 0,
      hbTimer: null,
      reconnectTimer: null,
      opts: { url, onOpen, onMessage, onError, onClose, autoReconnect },
    };
    slotsRef.current[id] = slot;

    const connect = () => {
      const ws = new WebSocket(url);
      slot.socket = ws;

      ws.onopen = (event) => {
        slot.attempts = 0;
        slot.hbTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try {
              ws.send(JSON.stringify({ type: 'ping' }));
            } catch {
              /* ignore */
            }
          }
        }, HEARTBEAT_INTERVAL_MS);
        onOpen?.(event, ws);
      };

      ws.onmessage = (event) => {
        onMessage?.(event);
      };

      ws.onerror = (event) => {
        onError?.(event);
      };

      ws.onclose = (event) => {
        _clearTimers(slot);
        onClose?.(event);

        const stillRegistered = slotsRef.current[id] === slot;
        const shouldReconnect =
          autoReconnect &&
          stillRegistered &&
          event.code !== 1000 &&
          slot.attempts < RECONNECT_MAX_ATTEMPTS;

        if (shouldReconnect) {
          const delay = Math.min(
            RECONNECT_BASE_DELAY_MS * Math.pow(2, slot.attempts),
            RECONNECT_MAX_DELAY_MS
          );
          slot.attempts += 1;
          slot.reconnectTimer = setTimeout(() => {
            if (slotsRef.current[id] === slot) {
              connect();
            }
          }, delay);
        } else if (stillRegistered) {
          delete slotsRef.current[id];
        }
      };
    };

    connect();
  }, [closeSocket]);

  const sendMessage = useCallback((id, payload) => {
    const slot = slotsRef.current[id];
    if (!slot || !slot.socket) return false;
    if (slot.socket.readyState !== WebSocket.OPEN) return false;
    const data = typeof payload === 'string' ? payload : JSON.stringify(payload);
    slot.socket.send(data);
    return true;
  }, []);

  // Hook 卸載時關掉所有連線，避免 memory leak
  useEffect(() => {
    return () => {
      Object.keys(slotsRef.current).forEach((id) => {
        const slot = slotsRef.current[id];
        if (!slot) return;
        _clearTimers(slot);
        try {
          slot.socket?.close(1000);
        } catch {
          /* ignore */
        }
      });
      slotsRef.current = {};
    };
  }, []);

  return { openSocket, closeSocket, closeAll, sendMessage };
}
