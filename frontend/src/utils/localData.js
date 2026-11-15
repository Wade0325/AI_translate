/**
 * 設定頁「資料與隱私」的文字（#231 Q1、Q7）。資料來自後端 GET /local-data：
 *
 *   { data_folder, retained_audio: { enabled, retention_days, folder, file_count, total_bytes } }
 *
 * data_folder 只有免安裝模式有；retention_days 是 0 時不自動刪除。保留音檔的天數與開關只能用
 * 環境變數改（AUDIO_RETENTION_DAYS、RETAIN_AUDIO），畫面只照實說明。
 */

/**
 * 保留音檔留多久：過期的只在啟動時清掃，看檔案的修改時間。天數從上傳時算起；寫入校正或確認狀態時
 * 後端把修改時間改成現在，所以校正過或標過確認狀態的任務從最後一次寫入起算（#350）。
 */
export function retentionNote(retained) {
  if (!retained.enabled) return '保留音檔已關閉：轉錄結束後就刪掉上傳的音檔。';
  const kept = '轉錄結束後（不論成功、失敗或取消），音檔會留在下面的資料夾，日後校正時可以重聽。';
  if (retained.retention_days <= 0) return `${kept}不會自動刪除。`;
  return `${kept}留 ${retained.retention_days} 天，從上傳時算起；校正過或標過確認狀態的任務，`
    + '從最後一次校正或標確認狀態起算。超過的在下次開啟 app 時刪除。';
}

/** 按「立即刪除全部保留音檔」之後的結果：{ deleted, failed }，刪不掉的多半是正被開著的檔案。 */
export function deletedMessage({ deleted, failed }) {
  const done = `已刪除 ${deleted} 個保留音檔`;
  return failed > 0 ? `${done}；${failed} 個正在使用中，沒刪掉，請稍後再試` : done;
}
