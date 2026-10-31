import { describe, expect, it } from 'vitest';
import { downloadProgress, formatWeightsSize } from './weightsDownload.js';

// 預設模型的兩份權重在釘住的版本合計 3,680,402,102 位元組，下載按鈕寫「~3.7 GB」
const DEFAULT_TOTAL = 3_680_402_102;

describe('formatWeightsSize：和下載按鈕一樣用十進位的 GB', () => {
  it('預設模型的總大小和按鈕寫的一樣是 3.7 GB', () => {
    expect(formatWeightsSize(DEFAULT_TOTAL)).toBe('3.7 GB');
  });

  it('不到 1 GB 改用 MB，剛開始下載時也看得到數字在動', () => {
    expect(formatWeightsSize(4_393_977)).toBe('4 MB');
    expect(formatWeightsSize(0)).toBe('0 MB');
  });
});

describe('downloadProgress：權重下載的進度（以位元組計算）', () => {
  it('照已下載的位元組算百分比，並寫出已下載多少', () => {
    expect(downloadProgress({ downloaded_bytes: 1_400_000_000, total_bytes: DEFAULT_TOTAL })).toEqual({
      percent: 38, text: '已下載 1.4 GB / 3.7 GB',
    });
  });

  it('還沒下載完不顯示 100%', () => {
    expect(downloadProgress({ downloaded_bytes: DEFAULT_TOTAL - 1, total_bytes: DEFAULT_TOTAL }).percent).toBe(99);
  });

  it('後端還在問檔案大小時是 0%，說明正在做什麼', () => {
    expect(downloadProgress({ downloaded_bytes: null, total_bytes: null })).toEqual({
      percent: 0, text: '正在向 Hugging Face 確認要下載的檔案…',
    });
  });
});
