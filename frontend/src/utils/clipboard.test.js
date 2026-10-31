import { describe, expect, it } from 'vitest';
import { copyText } from './clipboard.js';

describe('copyText：設定頁「複製診斷資訊」放進剪貼簿', () => {
  it('寫進剪貼簿並回傳 true', async () => {
    const written = [];
    const clipboard = { writeText: async (text) => { written.push(text); } };

    expect(await copyText('診斷資訊\n- 版本：dev\n', clipboard)).toBe(true);
    expect(written).toEqual(['診斷資訊\n- 版本：dev\n']);
  });

  it('使用者拒絕權限時回傳 false，不丟例外', async () => {
    const clipboard = { writeText: async () => { throw new DOMException('denied', 'NotAllowedError'); } };

    expect(await copyText('診斷資訊', clipboard)).toBe(false);
  });

  it('瀏覽器沒有剪貼簿（不安全的網址）時回傳 false', async () => {
    expect(await copyText('診斷資訊', undefined)).toBe(false);
  });
});
