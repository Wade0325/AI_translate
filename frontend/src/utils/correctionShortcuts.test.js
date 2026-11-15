import { describe, it, expect } from 'vitest';
import { SHORTCUT_GROUPS, shortcutAction } from './correctionShortcuts';

/** 不在打字時的鍵盤事件裡用得到的欄位；沒寫的是沒按、不是按住不放。 */
const key = (k, fields = {}) => ({
  key: k, code: '', shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, repeat: false, ...fields,
});

describe('shortcutAction：不在打字時按的鍵（#349）', () => {
  it.each([
    [' ', 'toggle-playback'],
    ['ArrowUp', 'previous'],
    ['ArrowDown', 'next'],
    ['ArrowLeft', 'rewind'],
    ['ArrowRight', 'forward'],
    ['Enter', 'edit'],
    ['v', 'verify'],
    ['f', 'flag'],
    ['r', 'replay'],
  ])('%j → %s', (k, action) => {
    expect(shortcutAction(key(k), null)).toBe(action);
  });

  it('大寫（開著 Caps Lock 或按著 Shift）也算', () => {
    expect(shortcutAction(key('V', { shiftKey: true }), null)).toBe('verify');
    expect(shortcutAction(key('F'), null)).toBe('flag');
    expect(shortcutAction(key('R'), null)).toBe('replay');
  });

  it('鍵盤配置打不出英文字母時（例如俄文），照鍵的位置認 V、F、R', () => {
    expect(shortcutAction(key('м', { code: 'KeyV' }), null)).toBe('verify');
    expect(shortcutAction(key('а', { code: 'KeyF' }), null)).toBe('flag');
    expect(shortcutAction(key('к', { code: 'KeyR' }), null)).toBe('replay');
  });

  it('打得出英文字母的配置照打出來的字認，不看位置（例如 Dvorak 在 V 的位置打出 k）', () => {
    expect(shortcutAction(key('k', { code: 'KeyV' }), null)).toBeNull();
    expect(shortcutAction(key('v', { code: 'Period' }), null)).toBe('verify');
  });

  it('其他的鍵不是快捷鍵', () => {
    for (const k of ['a', 'Escape', 'Tab', 'PageDown', 'Home', 'Backspace', '?', 'F5']) {
      expect(shortcutAction(key(k), null)).toBeNull();
    }
  });

  it('打字時一律不觸發：文字框自己用這些鍵（打字時的鍵見 editingKeyAction）', () => {
    for (const k of [' ', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'v', 'f', 'r']) {
      expect(shortcutAction(key(k), 'text')).toBeNull();
    }
  });

  it('選單或對話框打開時，按鍵是給它們的', () => {
    for (const k of [' ', 'ArrowDown', 'Enter', 'v']) {
      expect(shortcutAction(key(k), 'popup')).toBeNull();
    }
  });

  it('焦點在按鈕上時，空白鍵與 Enter 照常按下那個按鈕；其他快捷鍵照常', () => {
    expect(shortcutAction(key(' '), 'pressable')).toBeNull();
    expect(shortcutAction(key('Enter'), 'pressable')).toBeNull();
    expect(shortcutAction(key('ArrowDown'), 'pressable')).toBe('next');
    expect(shortcutAction(key('v'), 'pressable')).toBe('verify');
  });

  it('焦點在滑桿（播放進度）上時，方向鍵照常移動滑桿；其他快捷鍵照常', () => {
    for (const k of ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']) {
      expect(shortcutAction(key(k), 'slider')).toBeNull();
    }
    expect(shortcutAction(key(' '), 'slider')).toBe('toggle-playback');
    expect(shortcutAction(key('f'), 'slider')).toBe('flag');
  });

  it('按著 Ctrl、Alt 或 Command 時是瀏覽器與系統的鍵（Ctrl+F 開頁面的尋找在 #356）', () => {
    for (const modifier of ['ctrlKey', 'altKey', 'metaKey']) {
      expect(shortcutAction(key('f', { [modifier]: true }), null)).toBeNull();
      expect(shortcutAction(key('ArrowDown', { [modifier]: true }), null)).toBeNull();
    }
  });

  it('按住不放：換片段與倒退、前進一直觸發；其他的只算第一下，按住 V 不會一路標下去', () => {
    for (const k of ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']) {
      expect(shortcutAction(key(k, { repeat: true }), null)).not.toBeNull();
    }
    for (const k of [' ', 'Enter', 'v', 'f', 'r']) {
      expect(shortcutAction(key(k, { repeat: true }), null)).toBeNull();
    }
  });
});

describe('SHORTCUT_GROUPS：頁面上列出的快捷鍵', () => {
  it('不在打字時的每一個快捷鍵都列出來了', () => {
    const listed = SHORTCUT_GROUPS[0].items.flatMap((item) => item.actions);
    expect(listed.sort()).toEqual(
      ['edit', 'flag', 'forward', 'next', 'previous', 'replay', 'rewind', 'toggle-playback', 'verify'],
    );
  });

  it('也列出打字時的鍵：Enter、Esc、Tab、Shift+Tab', () => {
    expect(SHORTCUT_GROUPS[1].title).toBe('打字時');
    expect(SHORTCUT_GROUPS[1].items.map((item) => item.keys)).toEqual([['Enter'], ['Esc'], ['Tab'], ['Shift+Tab']]);
  });
});
