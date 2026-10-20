import { describe, it, expect } from 'vitest';
import { renameExtension } from './download';

// 刻意失敗：確認 vitest 失敗時 CI 的 check 會變紅（#46 的驗收條件），驗證完就 revert
describe('刻意失敗（#46）', () => {
  it('故意斷言錯的檔名', () => {
    expect(renameExtension('interview.mp3', 'srt')).toBe('interview.mp3');
  });
});
