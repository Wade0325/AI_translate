import { describe, it, expect } from 'vitest';
import { ApiError } from '../services/api';
import {
  REWIND_SECONDS,
  deleteRequest,
  editRequest,
  editingKeyAction,
  isTypingTarget,
  isUserDeleted,
  normalizedText,
  restoreRequest,
  revertRequest,
  saveFailureMessage,
  savesReducer,
  shownText,
  undoMessage,
} from './segmentEditing';

/** 鍵盤事件裡用得到的欄位；沒寫的是沒按、不在選字。 */
const key = (k, fields = {}) => ({
  key: k, shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, isComposing: false, keyCode: 0, ...fields,
});

describe('editingKeyAction：打字時按的鍵（#348）', () => {
  it('Enter 存檔、Esc 放棄', () => {
    expect(editingKeyAction(key('Enter'))).toBe('save');
    expect(editingKeyAction(key('Escape'))).toBe('cancel');
  });

  it('Shift+Enter 也是存檔：文字只有一行，存的時候換行也會收成空白', () => {
    expect(editingKeyAction(key('Enter', { shiftKey: true }))).toBe('save');
  });

  it('Tab 播放或暫停，Shift+Tab 倒退 3 秒；兩個都由頁面處理，焦點不移走', () => {
    expect(editingKeyAction(key('Tab'))).toBe('toggle-playback');
    expect(editingKeyAction(key('Tab', { shiftKey: true }))).toBe('rewind');
    expect(REWIND_SECONDS).toBe(3);
  });

  it('輸入法選字中按的 Enter 不存檔，Esc 不放棄，Tab 也留給輸入法', () => {
    for (const k of ['Enter', 'Escape', 'Tab']) {
      expect(editingKeyAction(key(k, { isComposing: true }))).toBeNull();
    }
  });

  it('Safari 選完字那一下的 Enter（compositionend 之後才到，isComposing 是 false、keyCode 是 229）也不存檔', () => {
    expect(editingKeyAction(key('Enter', { keyCode: 229 }))).toBeNull();
  });

  it('空白鍵、方向鍵與一般的字照常是打字用的', () => {
    for (const k of [' ', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'a', '中', 'Backspace']) {
      expect(editingKeyAction(key(k))).toBeNull();
    }
  });

  it('不用 Ctrl+空白鍵控制播放：它是 Windows 中文輸入法的切換鍵', () => {
    expect(editingKeyAction(key(' ', { ctrlKey: true }))).toBeNull();
  });

  it('Ctrl、Alt 或 Command 加 Tab 是瀏覽器與系統的鍵，不攔', () => {
    expect(editingKeyAction(key('Tab', { ctrlKey: true }))).toBeNull();
    expect(editingKeyAction(key('Tab', { altKey: true }))).toBeNull();
    expect(editingKeyAction(key('Tab', { metaKey: true }))).toBeNull();
  });
});

describe('isTypingTarget：按鍵發生在打字的地方，不在打字時的快捷鍵不處理', () => {
  it('文字框與輸入框是', () => {
    expect(isTypingTarget({ tagName: 'TEXTAREA' })).toBe(true);
    expect(isTypingTarget({ tagName: 'INPUT' })).toBe(true);
    expect(isTypingTarget({ tagName: 'DIV', isContentEditable: true })).toBe(true);
  });

  it('列表本身、按鈕與沒有對象時不是', () => {
    expect(isTypingTarget({ tagName: 'DIV', isContentEditable: false })).toBe(false);
    expect(isTypingTarget({ tagName: 'BUTTON' })).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe('normalizedText：和後端存的時候同一個規則（backend/app/api/transcripts.py 的 _normalized_text）', () => {
  it('前後的空白去掉，換行連同前後的空白收成一個空白', () => {
    expect(normalizedText('  \n今天先看進度 \r\n\n 再討論。\t ')).toBe('今天先看進度 再討論。');
    expect(normalizedText('第一句\u2028第二句\x85第三句')).toBe('第一句 第二句 第三句');
  });

  it('中間的空白不動，照使用者打的字', () => {
    expect(normalizedText('Hello  world 软件')).toBe('Hello  world 软件');
  });
});

/** 沒有校正過的片段（形狀照 GET /transcripts/{task_uuid} 的片段）。 */
const segment = (fields = {}) => ({
  seg_key: '0.0001', start: 1.5, text: '今天先看進度', original_text: '今天先看進度', speaker: 'S0', original_speaker: 'S0',
  corrected: false, deleted: false, deleted_text: null, has_correction_records: false, ...fields,
});

describe('editRequest：改完要送出的 PATCH body', () => {
  it('文字有變時送出打的字，不替使用者轉換', () => {
    expect(editRequest(segment(), '今天先看进度')).toEqual({ text: '今天先看进度' });
  });

  it('前後的空白去掉、換行收成空白再送，存檔中寫的就是會存進去的樣子', () => {
    expect(editRequest(segment(), ' 今天先看\n進度吧 ')).toEqual({ text: '今天先看 進度吧' });
  });

  it('和現在的內容相同時不送（只差在前後的空白或換行也算相同）', () => {
    expect(editRequest(segment(), '今天先看進度')).toBeNull();
    expect(editRequest(segment(), ' 今天先看進度\n')).toBeNull();
  });

  it('清空就是刪掉這個片段', () => {
    expect(editRequest(segment(), '')).toEqual({ text: '' });
    expect(editRequest(segment(), '  \n ')).toEqual({ text: '' });
  });
});

describe('刪掉、還原與回到原始轉錄', () => {
  it('刪掉是把文字改成空的', () => {
    expect(deleteRequest()).toEqual({ text: '' });
  });

  it('還原送回刪掉之前的文字（改過再刪的，就是改過的文字）', () => {
    const deleted = segment({ text: '', corrected: true, deleted: true, deleted_text: '今天先看進度吧' });
    expect(restoreRequest(deleted)).toEqual({ text: '今天先看進度吧' });
  });

  it('使用者刪掉的才算刪掉；原始轉錄就沒有文字的片段照常可以改', () => {
    expect(isUserDeleted(segment({ text: '', corrected: true, deleted: true, deleted_text: '今天' }))).toBe(true);
    expect(isUserDeleted(segment({ text: '', original_text: '', deleted: true, deleted_text: null }))).toBe(false);
    expect(isUserDeleted(segment())).toBe(false);
  });

  it('回到原始轉錄：文字與說話者有變的都送回原始轉錄', () => {
    const corrected = segment({ text: '今天先看进度', speaker: 'S1', corrected: true });
    expect(revertRequest(corrected)).toEqual({ text: '今天先看進度', speaker: 'S0' });
    expect(revertRequest(segment({ text: '改過', corrected: true }))).toEqual({ text: '今天先看進度' });
    expect(revertRequest(segment({ speaker: 'S2', corrected: true }))).toEqual({ speaker: 'S0' });
  });

  it('原始轉錄沒有說話者時送 null（清除）', () => {
    expect(revertRequest(segment({ speaker: 'S1', original_speaker: null, corrected: true }))).toEqual({ speaker: null });
  });

  it('沒有校正過時沒有要送的', () => {
    expect(revertRequest(segment())).toBeNull();
  });
});

describe('savesReducer：每個片段的存檔狀態', () => {
  const saving = (saves, request = { text: '改過' }) => savesReducer(saves, { type: 'start', segKey: 'a', request });

  it('送出時是存檔中，成功是已存，幾秒之後收起來', () => {
    let saves = saving({});
    expect(saves.a).toEqual({ status: 'saving', request: { text: '改過' } });
    saves = savesReducer(saves, { type: 'succeed', segKey: 'a' });
    expect(saves.a).toEqual({ status: 'saved' });
    saves = savesReducer(saves, { type: 'settle', segKey: 'a' });
    expect(saves).toEqual({});
  });

  it('失敗時留著送出的內容與原因，重試再送一次同樣的內容', () => {
    let saves = savesReducer(saving({}), { type: 'fail', segKey: 'a', message: '連不上 Mimiji' });
    expect(saves.a).toEqual({ status: 'failed', request: { text: '改過' }, message: '連不上 Mimiji' });

    saves = saving(saves, { text: '改過' });
    expect(saves.a).toEqual({ status: 'saving', request: { text: '改過' } });
    saves = savesReducer(saves, { type: 'succeed', segKey: 'a' });
    expect(saves.a.status).toBe('saved');
  });

  it('失敗的內容可以放棄，回到存好的內容', () => {
    const saves = savesReducer(saving({}), { type: 'fail', segKey: 'a', message: 'x' });
    expect(savesReducer(saves, { type: 'discard', segKey: 'a' })).toEqual({});
  });

  it('收起「已存」時不動到之後又送出或失敗的', () => {
    const again = saving(savesReducer(saving({}), { type: 'succeed', segKey: 'a' }));
    expect(savesReducer(again, { type: 'settle', segKey: 'a' })).toBe(again);
    const failed = savesReducer(again, { type: 'fail', segKey: 'a', message: 'x' });
    expect(savesReducer(failed, { type: 'settle', segKey: 'a' })).toBe(failed);
  });

  it('只改動到那一個片段，其他片段的狀態是同一個物件（列表不必重畫那幾列）', () => {
    const before = saving({}, { text: '1' });
    const after = savesReducer(before, { type: 'start', segKey: 'b', request: { text: '2' } });
    expect(after.a).toBe(before.a);
  });
});

describe('shownText：片段那一列寫的文字', () => {
  it('存檔中與失敗時寫送出的內容，失敗時才不會看起來像沒打過', () => {
    expect(shownText(segment(), { status: 'saving', request: { text: '改過' } })).toBe('改過');
    expect(shownText(segment(), { status: 'failed', request: { text: '改過' }, message: 'x' })).toBe('改過');
  });

  it('沒有存檔狀態、已存，或送出的內容沒有文字時寫片段現在的文字', () => {
    expect(shownText(segment(), undefined)).toBe('今天先看進度');
    expect(shownText(segment(), { status: 'saved' })).toBe('今天先看進度');
    expect(shownText(segment(), { status: 'saving', request: { speaker: 'S1' } })).toBe('今天先看進度');
  });
});

describe('saveFailureMessage：存不進去時寫的原因', () => {
  it('後端擋下的請求寫後端給的那一句（例如太長、任務不能校正）', () => {
    expect(saveFailureMessage(new ApiError(400, '文字太長：一個片段最多 5000 字'))).toBe('文字太長：一個片段最多 5000 字');
    expect(saveFailureMessage(new ApiError(409, '這個任務還沒完成，完成之後才能校正'))).toBe('這個任務還沒完成，完成之後才能校正');
  });

  it('找不到任務或片段時，說明可能已經刪掉', () => {
    expect(saveFailureMessage(new ApiError(404, '找不到此片段'))).toBe('找不到這個任務或片段，可能已經在 History 刪掉了');
  });

  it('連不上或伺服器出錯時，請使用者確認 Mimiji 還在執行再重試', () => {
    expect(saveFailureMessage(new TypeError('Failed to fetch'))).toBe('連不上 Mimiji，確認它還在執行之後再重試');
    expect(saveFailureMessage(new ApiError(500, 'Internal Server Error'))).toBe('連不上 Mimiji，確認它還在執行之後再重試');
  });
});

describe('undoMessage：按了「復原」之後寫的結果', () => {
  it('全部還原', () => {
    expect(undoMessage({ restored: 1, skipped: 0 })).toEqual({ type: 'success', content: '已復原' });
  });

  it('之後又改過的沒有還原，寫出幾筆', () => {
    expect(undoMessage({ restored: 1, skipped: 1 }))
      .toEqual({ type: 'warning', content: '已復原；有 1 筆在這之後又改過，沒有復原' });
    expect(undoMessage({ restored: 0, skipped: 2 }))
      .toEqual({ type: 'warning', content: '這次校正之後又改過，沒有復原' });
  });
});
