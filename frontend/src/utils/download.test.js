import { describe, it, expect } from 'vitest';
import { renameExtension } from './download';

describe('renameExtension：下載的檔名沿用音檔的檔名，副檔名換成輸出格式', () => {
  it('換掉音檔的副檔名', () => {
    expect(renameExtension('interview.mp3', 'srt')).toBe('interview.srt');
  });

  it('檔名裡有好幾個點時只換最後一段', () => {
    expect(renameExtension('2026.10.20 會議.m4a', 'txt')).toBe('2026.10.20 會議.txt');
  });

  it('沒有副檔名時直接加上', () => {
    expect(renameExtension('recording', 'vtt')).toBe('recording.vtt');
  });

  it('點前面沒有主檔名時整個保留，不會只剩副檔名', () => {
    expect(renameExtension('.m4a', 'lrc')).toBe('.m4a.lrc');
  });
});
