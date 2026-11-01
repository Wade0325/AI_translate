/**
 * 送出任務之後和伺服器的連線斷了（單檔任務 #280、批次 #286）：檔案卡要寫什麼。
 *
 * 連線斷了不會停止任務，任務照樣在伺服器上跑，結果寫進任務紀錄。畫面重新連上伺服器、接回這個任務
 * 或這一批（hooks/useUploadQueue.js；伺服器那一端是 backend/app/api/transcription.py 的
 * reattach_endpoint 與 backend/app/api/batch.py 的 batch_reattach_endpoint），接回之前檔案卡仍是
 * 處理中，另外記下連線的狀況（檔案卡的 connection），寫出原因與下一步：
 *
 *   - LOST：連線斷了，正在重新連線
 *   - UNREACHABLE：重新連線時伺服器一則都沒回就斷了，多半是 Mimiji 已經關閉（例如關掉了免安裝版的
 *     黑色視窗）。畫面照樣每隔一段時間再連一次，重新開啟之後自動接回
 *
 * 接回之後收到的第一則狀態訊息就清掉它（fileResult.js 的 applyFileResult、batchStatus.js）：任務還在跑
 * 就接著顯示進度，已經結束就照任務紀錄顯示結果，伺服器上已經沒有這個任務（例如還沒做完就重新啟動了）
 * 就顯示失敗。
 */

export const CONNECTION = Object.freeze({
  LOST: 'lost',
  UNREACHABLE: 'unreachable',
});

const COPY = Object.freeze({
  [CONNECTION.LOST]: {
    label: '連線中斷，正在重新連線...',
    reason: '和伺服器的連線中斷了',
    nextStep: '連線中斷不會停止任務，不必重新轉錄。重新連上之後，這裡會接著顯示進度與結果。',
    links: [],
  },
  [CONNECTION.UNREACHABLE]: {
    label: '連線中斷，連不上伺服器',
    reason: '連不上伺服器，Mimiji 可能已經關閉',
    nextStep: '請重新開啟 Mimiji（免安裝版是 AI_Translate.exe；關掉它的黑色視窗就會停止）。'
      + '重新開啟之後，這裡會自動接回任務；也可以到任務頁或歷史紀錄查看。',
    links: [
      { label: '任務頁', to: '/tasks' },
      { label: '歷史紀錄', to: '/history' },
    ],
  },
});

/** 檔案卡記下連線的狀況（CONNECTION 的其中一個）；任務本身的狀態不動，仍是處理中。 */
export function connectionLost(file, connection) {
  return { ...file, connection };
}

/** 又和伺服器接上了：拿掉檔案卡上連線中斷的記號。 */
export function connectionRestored(file) {
  // eslint-disable-next-line no-unused-vars -- 拿掉連線中斷的記號
  const { connection, ...rest } = file;
  return rest;
}

/**
 * 要顯示的內容：{ label, reason, nextStep, links }。label 是檔案卡狀態標籤上的字，reason 與 nextStep
 * 寫在檔案卡下方，links 是前往查看的連結（{ label, to }）。認不得的狀況時是 null。
 */
export function describeConnection(connection) {
  return COPY[connection] ?? null;
}
