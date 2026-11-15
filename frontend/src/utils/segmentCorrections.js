import { ApiError } from '../services/api';

/**
 * 校正頁改文字（#348）不依賴畫面的部分：打字時的按鍵、要送出什麼、每個片段的存檔狀態，以及寫給使用者看的結果。
 *
 * 每一次校正就是一個 PATCH /transcripts/{task_uuid}/segments/{seg_key}（backend/app/api/transcripts.py），
 * 沒有整頁的存檔鈕。刪掉片段是把文字改成空的；還原、回到原始轉錄都是把那一版的內容當成一次普通的校正送出
 * （ADR 0011），不另開端點。
 *
 * @typedef {{ seg_key: string, start: number, end?: number | null, text: string, original_text: string,
 *   speaker?: string | null, original_speaker?: string | null, corrected: boolean, deleted: boolean,
 *   deleted_text?: string | null, has_correction_records: boolean,
 *   words?: { text?: string | null, start: number, end?: number | null }[] | null }} Segment
 *   GET /transcripts/{task_uuid} 的一個片段（校正後版本加上原始轉錄）
 * @typedef {{ text?: string, speaker?: string | null }} SegmentRequest PATCH 的 body
 * @typedef {{ status: 'saving', request: SegmentRequest }
 *   | { status: 'saved' }
 *   | { status: 'failed', request: SegmentRequest, message: string }} SaveState 一個片段的存檔狀態
 * @typedef {Record<string, SaveState>} Saves 每個片段的存檔狀態，鍵是 seg_key；沒有存檔狀態的片段不在裡面
 * @typedef {{ start: number, end: number }} TextSelection 游標（或選取的範圍）在片段文字裡的位置
 * @typedef {{ segKey: string, selection: TextSelection | null }} Editing
 *   正在改的片段；selection 是開始改時游標放的地方，null 時放在最後
 * @typedef {'toggle-playback' | 'rewind'} PlaybackAction 打字時控制播放的鍵：Tab 播放或暫停，Shift+Tab 倒退
 * @typedef {'save' | 'cancel' | PlaybackAction} EditingAction 打字時按的鍵要做的事
 */

/** 打字時 Shift+Tab 倒退幾秒。 */
export const REWIND_SECONDS = 3;

/** 輸入法選字中：Safari 選完字那一下的 Enter 在 compositionend 之後才到，isComposing 已經是 false，keyCode 是 229。 */
function composing(event) {
  return event.isComposing || event.keyCode === 229;
}

/**
 * 打字時按的鍵要做什麼（#345 第 7 節「打字時」）。回 null 的鍵照常交給文字框：空白鍵與方向鍵是打字用的，
 * 不觸發任何快捷鍵。有回動作的鍵，呼叫的人要 preventDefault：Enter 不換行，Tab 與 Shift+Tab 不把焦點移走。
 *
 * - 輸入法選字中按的鍵一律交給輸入法：選字的 Enter 不算存檔，Esc 不放棄這次輸入，有的輸入法用 Tab 換候選字。
 * - 不用 Ctrl+空白鍵控制播放，它是 Windows 中文輸入法的切換鍵。Ctrl、Alt、Command 加 Tab 是瀏覽器與系統的鍵。
 *
 * @param {{ key: string, shiftKey: boolean, ctrlKey: boolean, altKey: boolean, metaKey: boolean,
 *   isComposing: boolean, keyCode: number }} event 鍵盤事件（React 的事件也有這些欄位）
 * @returns {EditingAction | null}
 */
export function editingKeyAction(event) {
  if (composing(event)) return null;
  if (event.key === 'Enter') return 'save';
  if (event.key === 'Escape') return 'cancel';
  if (event.key === 'Tab' && !event.ctrlKey && !event.altKey && !event.metaKey) {
    return event.shiftKey ? 'rewind' : 'toggle-playback';
  }
  return null;
}

/**
 * 按鍵發生在打字的地方（文字框、輸入框、可以編輯的元素）：不在打字時的快捷鍵與捲動列表的處理都略過它。
 *
 * @param {{ tagName?: string, isContentEditable?: boolean } | null | undefined} target 事件的對象
 */
export function isTypingTarget(target) {
  if (!target) return false;
  return target.tagName === 'TEXTAREA' || target.tagName === 'INPUT' || target.isContentEditable === true;
}

/**
 * 正在改文字時，按片段或頁面上的按鈕不讓文字框失去焦點（給按鈕的 onMouseDown）：按鈕自己決定要不要存，例如刪除
 * 就不存打到一半的字；「復原」收回的是剛存的另一次，正在打的字照樣留著。
 *
 * @param {{ preventDefault: () => void }} event
 */
export function keepEditorFocus(event) {
  event.preventDefault();
}

/** 換行，連同它前後的空白（和後端的 _LINE_BREAKS 相同）。 */
// eslint-disable-next-line no-control-regex -- 垂直定位、換頁與分隔字元是 str.splitlines 當成換行的字元，和後端同一組
const LINE_BREAKS = /\s*[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]+\s*/gu;

/**
 * 文字存進去的樣子：前後的空白去掉，換行連同前後的空白收成一個空白，其他照使用者打的字（不做繁體輸出的轉換）。
 * 和後端存的時候同一個規則（backend/app/api/transcripts.py 的 _normalized_text）：送出前先收好，存檔中畫面寫的
 * 就是會存進去的樣子；有沒有改也照它判斷。
 *
 * @param {string} text
 */
export function normalizedText(text) {
  return text.trim().replace(LINE_BREAKS, ' ');
}

/**
 * 改完文字要送出的 PATCH body（收成一行的文字）；和片段現在的文字相同時是 null，不送。清空就是刪掉這個片段。
 *
 * @param {Segment} segment
 * @param {string} draft 文字框裡的內容
 * @returns {SegmentRequest | null}
 */
export function correctTextRequest(segment, draft) {
  const text = normalizedText(draft);
  return text === normalizedText(segment.text ?? '') ? null : { text };
}

/** 刪掉片段：把文字改成空的。刪掉的片段留在原位，可以還原。 */
export function deleteRequest() {
  return { text: '' };
}

/**
 * 使用者刪掉的片段：文字是空的，而且有刪掉之前的文字可以還原。原始轉錄就沒有文字的片段，後端也當成刪掉的
 * 片段（下載時略過），但它不是使用者刪的，照常可以點文字改。
 *
 * @param {Segment} segment
 */
export function isUserDeleted(segment) {
  return segment.deleted && Boolean(segment.deleted_text);
}

/**
 * 還原刪掉的片段：送回刪掉之前的文字（後端的 deleted_text）。改過再刪掉的，還原成改過的文字。
 *
 * @param {Segment} segment
 * @returns {SegmentRequest}
 */
export function restoreRequest(segment) {
  return { text: segment.deleted_text || segment.original_text };
}

/**
 * 說話者校正過：和原始轉錄的說話者不同（沒有說話者當成同一個值）。
 *
 * @param {Segment} segment
 */
export function speakerCorrected(segment) {
  return (segment.speaker ?? null) !== (segment.original_speaker ?? null);
}

/**
 * 回到原始轉錄：文字與說話者有變的都送回原始轉錄，後端各記一筆、共用一個操作編號。沒有校正過時是 null。
 *
 * @param {Segment} segment
 * @returns {SegmentRequest | null}
 */
export function revertRequest(segment) {
  /** @type {SegmentRequest} */
  const request = {};
  if ((segment.text ?? '') !== (segment.original_text ?? '')) request.text = segment.original_text ?? '';
  if (speakerCorrected(segment)) request.speaker = segment.original_speaker ?? null;
  return Object.keys(request).length ? request : null;
}

/**
 * 每個片段的存檔狀態怎麼變：
 *
 * - start：送出 request，存檔中。重試就是再 start 一次失敗時留下的 request。
 * - succeed：已存。過幾秒由 settle 收起來。
 * - fail：存檔失敗，留著送出的內容（畫面照它顯示，可以重試）與原因。
 * - settle：收起「已存」；之後又送出或失敗的不動。
 * - discard：放棄失敗的內容，回到存好的內容。
 *
 * 沒改到的片段保留同一個物件，列表只重畫改到的那幾列。
 *
 * @param {Saves} saves
 * @param {{ type: 'start', segKey: string, request: SegmentRequest }
 *   | { type: 'succeed' | 'settle' | 'discard', segKey: string }
 *   | { type: 'fail', segKey: string, message: string }} action
 * @returns {Saves}
 */
export function savesReducer(saves, action) {
  const { segKey } = action;
  const current = saves[segKey];
  switch (action.type) {
    case 'start':
      return { ...saves, [segKey]: { status: 'saving', request: action.request } };
    case 'succeed':
      return { ...saves, [segKey]: { status: 'saved' } };
    case 'fail':
      return { ...saves, [segKey]: { status: 'failed', request: current?.status === 'saving' ? current.request : {}, message: action.message } };
    case 'settle':
      return current?.status === 'saved' ? without(saves, segKey) : saves;
    case 'discard':
      return current ? without(saves, segKey) : saves;
    default:
      return saves;
  }
}

function without(saves, segKey) {
  const rest = { ...saves };
  delete rest[segKey];
  return rest;
}

/**
 * 片段那一列寫的文字：存檔中與失敗時寫送出的內容（失敗時打的字才不會看起來不見了），其他時候寫片段現在的文字。
 *
 * @param {Segment} segment
 * @param {SaveState | undefined} save
 */
export function shownText(segment, save) {
  if (save && save.status !== 'saved' && typeof save.request.text === 'string') return save.request.text;
  return segment.text ?? '';
}

const UNREACHABLE = '連不上 Mimiji，確認它還在執行之後再重試';
const GONE = '找不到這個任務或片段，可能已經在 History 刪掉了';

/**
 * 存不進去時寫給使用者看的原因。後端擋下的請求（文字太長、任務不能校正）寫後端給的那一句；連不上或伺服器
 * 出錯時請使用者確認 Mimiji 還在執行再重試。
 *
 * @param {unknown} error
 */
export function saveFailureMessage(error) {
  if (!(error instanceof ApiError) || error.status >= 500) return UNREACHABLE;
  if (error.status === 404) return GONE;
  return error.message || UNREACHABLE;
}

/**
 * 按了「復原」之後寫的結果（給 antd message）。復原只還原那次操作之後沒再改過的；之後又改過的略過，寫出幾筆。
 *
 * @param {{ restored: number, skipped: number }} result 復原端點的回應
 * @returns {{ type: 'success' | 'warning', content: string }}
 */
export function undoMessage({ restored, skipped }) {
  if (!skipped) return { type: 'success', content: '已復原' };
  if (!restored) return { type: 'warning', content: '這次校正之後又改過，沒有復原' };
  return { type: 'warning', content: `已復原；有 ${skipped} 筆在這之後又改過，沒有復原` };
}
