/**
 * 轉錄結果可能掉尾（#257）：一段送去轉錄的音檔，最後一句之後還有聲音，轉錄結果卻沒有內容，例如模型
 * 提早停止了輸出。後端找出可能掉尾的起點（backend/app/services/tail_loss.py），完成時隨結果送來
 * （tail_loss_from_seconds，原音檔的秒數），任務紀錄也記著；轉錄頁的檔案卡、結果頁與 History 照它寫出
 * 從哪裡起可能沒有轉錄到。
 *
 * 後端只看音量判斷有沒有聲音，片尾音樂與環境音也算，所以寫「可能」，下一步也請使用者先聽一下。
 */
import { formatClock } from './formatters';

const NEXT_STEP = '從這裡起有一段聲音沒有對應的轉錄結果，模型可能提早停止了輸出。請聽一下原音檔的這一段：'
  + '只是音樂或環境音就不必理會；有說話的話，可以把這一段剪成另一個檔案再轉錄。';

/**
 * 要顯示的內容：{ reason, nextStep }。seconds 是可能掉尾的起點（原音檔的秒數）；沒有掉尾（null、
 * undefined）時是 null。
 */
export function describeTailLoss(seconds) {
  if (seconds === null || seconds === undefined) return null;
  return { reason: `從 ${formatClock(seconds)} 起可能沒有轉錄到`, nextStep: NEXT_STEP };
}
