/**
 * 按取消之後顯示的訊息：取消端點（POST /transcription/{file_uid}/cancel）的回應對應到 antd
 * message.open 的設定 { type, content }。純函式，不碰 React 與網路。
 *
 * 沒有取消時，後端用 reason 說明原因（#126），兩種要分開講，使用者才知道要不要再按一次：
 *   - not-started：任務還沒提交到佇列（可能還在上傳），稍後再按就能取消；
 *   - finished：任務已經結束（完成或失敗），或正在收尾，來不及取消。結果馬上會出現在檔案卡上。
 */

export function cancelNotice(response, fileName) {
  if (response.cancelled) {
    return { type: 'info', content: `已取消任務：${fileName}` };
  }
  switch (response.reason) {
    case 'not-started':
      return { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' };
    case 'finished':
      return { type: 'info', content: '任務已經結束，無法取消。' };
    default:
      // 認不得的原因不猜是哪一種：說錯原因正是 #161 要修的問題
      return { type: 'warning', content: '任務沒有取消，請稍後再試。' };
  }
}
