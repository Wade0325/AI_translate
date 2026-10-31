/**
 * 把文字放進剪貼簿；成功回傳 true。
 *
 * 瀏覽器只在安全的網址（https、localhost、127.0.0.1）提供剪貼簿：用區網 IP 開 Docker 模式時沒有
 * navigator.clipboard，使用者拒絕權限時 writeText 會失敗。兩種都回傳 false，畫面改請使用者自己選取複製。
 *
 * @param {string} text
 * @param {Pick<Clipboard, 'writeText'> | undefined} [clipboard] 測試時換成假的；省略就用瀏覽器的
 * @returns {Promise<boolean>}
 */
export async function copyText(text, clipboard = globalThis.navigator?.clipboard) {
  if (!clipboard?.writeText) return false;
  try {
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
