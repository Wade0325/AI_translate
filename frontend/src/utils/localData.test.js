import { describe, expect, it } from 'vitest';
import { deletedMessage, retentionNote } from './localData.js';

const RETAINED = { enabled: true, retention_days: 30, folder: 'D:\\AI_Translate\\data\\audio_store', file_count: 2, total_bytes: 10 };

describe('retentionNote：設定頁說明保留音檔留多久（#231 Q1）', () => {
  it('照設定的天數說明，超過的在下次開啟時刪除', () => {
    expect(retentionNote(RETAINED)).toBe(
      '轉錄結束後（不論成功、失敗或取消），音檔會留在下面的資料夾，日後校正時可以重聽。上傳超過 30 天的，在下次開啟 app 時刪除。');
  });

  it('天數是 0 時不會自動刪除', () => {
    expect(retentionNote({ ...RETAINED, retention_days: 0 })).toBe(
      '轉錄結束後（不論成功、失敗或取消），音檔會留在下面的資料夾，日後校正時可以重聽。不會自動刪除。');
  });

  it('關掉保留音檔時說明轉錄結束就刪掉', () => {
    expect(retentionNote({ ...RETAINED, enabled: false })).toBe('保留音檔已關閉：轉錄結束後就刪掉上傳的音檔。');
  });
});

describe('deletedMessage：按「立即刪除」之後的結果', () => {
  it('全部刪掉', () => {
    expect(deletedMessage({ deleted: 3, failed: 0 })).toBe('已刪除 3 個保留音檔');
  });

  it('有刪不掉的就照實說，請使用者稍後再試', () => {
    expect(deletedMessage({ deleted: 2, failed: 1 })).toBe('已刪除 2 個保留音檔；1 個正在使用中，沒刪掉，請稍後再試');
  });
});
