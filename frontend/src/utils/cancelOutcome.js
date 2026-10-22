/**
 * 按取消之後：取消端點（POST /transcription/{file_uid}/cancel）的回應對應到有沒有取消，以及要顯示
 * 的提示（antd message.open 的設定 { type, content }）。純函式，不碰 React 與網路。
 *
 *   { file_uid, cancelled: true }
 *   { file_uid, cancelled: false, reason: 'not-started' | 'finished' }
 *
 * 端點的回應只在這個檔案讀：tests/integration/test_provider_seam.py 對照端點，確認端點回的每一種
 * 原因這裡都認得。沒有取消時，後端用 reason 說明原因（#126），兩種要分開講，使用者才知道要不要
 * 再按一次（#161）：
 *   - not-started：後端查不到任務的登記。多半是任務還沒提交到佇列（可能還在上傳），稍後再按就能
 *     取消；任務結束、登記已經清掉時也是這個原因。
 *   - finished：任務已經結束（完成或失敗），或已經記下結果、正在收尾，來不及取消。
 */

export function cancelOutcome(response, fileName) {
  if (response?.cancelled === true) {
    return { cancelled: true, notice: { type: 'info', content: `已取消任務：${fileName}` } };
  }
  return { cancelled: false, notice: notCancelledNotice(response?.reason) };
}

function notCancelledNotice(reason) {
  switch (reason) {
    case 'not-started':
      return { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' };
    case 'finished':
      return { type: 'info', content: '任務已經結束，無法取消。' };
    default:
      // 認不得的原因不猜是哪一種，也不叫使用者再按：說錯原因正是 #161 要修的問題
      return { type: 'warning', content: '任務沒有取消。' };
  }
}
