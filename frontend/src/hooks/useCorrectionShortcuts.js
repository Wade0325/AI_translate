import { useEffect, useLayoutEffect, useRef } from 'react';
import { keyOwner, shortcutAction } from '../utils/correctionShortcuts';

/**
 * 校正頁不在打字時的快捷鍵（#349）：整頁聽鍵盤，按鍵照 shortcutAction 對應到動作，交給 onShortcut。
 *
 * 有對應的鍵一律 preventDefault（空白鍵與方向鍵不捲動，Enter 不會在剛打開的文字框裡換行），即使這時做不了
 * 那個動作（例如保留音檔不在時按空白鍵）。別的元件已經處理掉的鍵（defaultPrevented）不動。enabled 是 false 時
 * （例如確認的對話框打開時）整個不聽。
 *
 * @param {(action: import('../utils/correctionShortcuts').ShortcutAction) => void} onShortcut 每次都可以是新的函式
 * @param {boolean} enabled
 */
export function useCorrectionShortcuts(onShortcut, enabled) {
  const latest = useRef(onShortcut);
  useLayoutEffect(() => {
    latest.current = onShortcut;
  });

  useEffect(() => {
    if (!enabled) return undefined;
    const onKeyDown = (event) => {
      if (event.defaultPrevented) return;
      const action = shortcutAction(event, keyOwner(event.target));
      if (!action) return;
      event.preventDefault();
      latest.current(action);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled]);
}
