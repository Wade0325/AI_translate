import { REWIND_SECONDS, isTypingTarget } from './segmentCorrections';

/**
 * 校正頁不在打字時的快捷鍵（#349，#345 第 7 節）：按鍵對應到什麼動作，以及頁面上列出的快捷鍵。打字時的鍵
 * （Enter、Esc、Tab、Shift+Tab）在 segmentCorrections.js 的 editingKeyAction，這裡只列出來。
 *
 * 按鍵怎麼對應是純函式（shortcutAction），焦點在什麼元素上由 keyOwner 從畫面判斷，兩者分開：前者用單元測試，
 * 後者在瀏覽器測試裡驗。
 *
 * @typedef {'toggle-playback' | 'previous' | 'next' | 'rewind' | 'forward' | 'edit' | 'verify' | 'flag' | 'replay'}
 *   ShortcutAction
 * @typedef {'text' | 'popup' | 'slider' | 'pressable' | null} KeyOwner
 *   焦點所在的元素自己要用哪些鍵：text 是打字的地方（全部的鍵），popup 是打開的選單或對話框（全部的鍵），
 *   slider 是滑桿（方向鍵），pressable 是按鈕、連結這類按下去的元素（空白鍵與 Enter）；null 是都不用
 * @typedef {{ key: string, code?: string, ctrlKey: boolean, altKey: boolean, metaKey: boolean, repeat: boolean }}
 *   ShortcutEvent 鍵盤事件（瀏覽器的 KeyboardEvent 也有這些欄位）
 */

/** @type {Record<string, ShortcutAction>} */
const KEY_ACTIONS = {
  ' ': 'toggle-playback',
  ArrowUp: 'previous',
  ArrowDown: 'next',
  ArrowLeft: 'rewind',
  ArrowRight: 'forward',
  Enter: 'edit',
  v: 'verify',
  f: 'flag',
  r: 'replay',
};

/** 按住不放時一直觸發的：換片段與倒退、前進。其他的只算第一下，按住 V 不會一路標下去。 */
const REPEATABLE = new Set(['previous', 'next', 'rewind', 'forward']);

const ARROWS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']);

/**
 * 按鍵打出來的英文字母（小寫）。鍵盤配置打不出英文字母時（例如俄文），照鍵的位置（KeyV → v）：快捷鍵寫的是
 * V、F、R 這幾個字，打得出英文字母的配置（例如 Dvorak）照打出來的字認。
 *
 * @param {ShortcutEvent} event
 */
function letterOf(event) {
  if (/^[a-z]$/i.test(event.key)) return event.key.toLowerCase();
  if (event.key.length === 1) return /^Key([A-Z])$/.exec(event.code ?? '')?.[1].toLowerCase() ?? event.key;
  return event.key;
}

/**
 * 不在打字時按的鍵要做什麼；不是快捷鍵時是 null。有回動作的鍵，呼叫的人要 preventDefault：空白鍵與方向鍵不捲動
 * 頁面，Enter 不會在剛打開的文字框裡換行。
 *
 * - 打字時（owner 是 text）一律不觸發，只有打字時的那幾個鍵（editingKeyAction）。選單或對話框打開時也不觸發。
 * - 焦點在按鈕上時，空白鍵與 Enter 照常按下那個按鈕；在滑桿（播放進度）上時，方向鍵照常移動滑桿。
 * - 按著 Ctrl、Alt 或 Command 的是瀏覽器與系統的鍵，例如 Ctrl+F 開頁面自己的尋找（#356）。
 *
 * @param {ShortcutEvent} event
 * @param {KeyOwner} owner 焦點所在的元素自己要用哪些鍵（keyOwner）
 * @returns {ShortcutAction | null}
 */
export function shortcutAction(event, owner) {
  if (owner === 'text' || owner === 'popup') return null;
  if (event.ctrlKey || event.altKey || event.metaKey) return null;
  const key = letterOf(event);
  const action = KEY_ACTIONS[key];
  if (!action) return null;
  if (event.repeat && !REPEATABLE.has(action)) return null;
  if (owner === 'pressable' && (key === ' ' || key === 'Enter')) return null;
  if (owner === 'slider' && ARROWS.has(key)) return null;
  return action;
}

/** 打開的選單、對話框、下拉清單：按鍵都是給它們的。 */
const POPUP = '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]';
const SLIDER = '[role="slider"]';
/** 按下去的元素：自己用空白鍵與 Enter。 */
const PRESSABLE = 'button, a[href], summary, [role="button"], [role="link"], [role="menuitem"], [role="tab"], '
  + '[role="checkbox"], [role="radio"], [role="switch"], [role="option"]';

/**
 * 焦點所在的元素（鍵盤事件的對象）自己要用哪些鍵，給 shortcutAction。
 *
 * @param {EventTarget | null} target
 * @returns {KeyOwner}
 */
export function keyOwner(target) {
  const element = /** @type {Element | null} */ (target);
  if (isTypingTarget(/** @type {HTMLElement | null} */ (element))) return 'text';
  if (typeof element?.closest !== 'function') return null;
  if (element.closest(POPUP)) return 'popup';
  if (element.closest(SLIDER)) return 'slider';
  if (element.closest(PRESSABLE)) return 'pressable';
  return null;
}

/**
 * 頁面上列出的快捷鍵（快捷鍵說明）。keys 是要按的鍵，列了好幾個的是其中一個都行（例如 ↑、↓）；actions 對到
 * shortcutAction 回的動作，單元測試用它檢查每個快捷鍵都列出來了。
 *
 * @type {{ title: string, items: { keys: string[], label: string, actions?: ShortcutAction[] }[] }[]}
 */
export const SHORTCUT_GROUPS = [
  {
    title: '不在打字時',
    items: [
      { keys: ['空白鍵'], label: '播放或暫停', actions: ['toggle-playback'] },
      { keys: ['↑', '↓'], label: '換到上一個、下一個片段', actions: ['previous', 'next'] },
      { keys: ['←', '→'], label: `倒退、前進 ${REWIND_SECONDS} 秒`, actions: ['rewind', 'forward'] },
      { keys: ['Enter'], label: '開始改目前這個片段的文字', actions: ['edit'] },
      { keys: ['V'], label: '標成已確認，換到下一個片段；再按一次是取消', actions: ['verify'] },
      { keys: ['F'], label: '標成待查，換到下一個片段；再按一次是取消', actions: ['flag'] },
      { keys: ['R'], label: '從頭重播目前這個片段', actions: ['replay'] },
    ],
  },
  {
    title: '打字時',
    items: [
      { keys: ['Enter'], label: '存檔' },
      { keys: ['Esc'], label: '放棄' },
      { keys: ['Tab'], label: '播放或暫停' },
      { keys: ['Shift+Tab'], label: `倒退 ${REWIND_SECONDS} 秒` },
    ],
  },
];
