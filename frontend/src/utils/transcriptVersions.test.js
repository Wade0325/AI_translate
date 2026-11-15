import { describe, expect, it } from 'vitest';
import { downloadMenuItems, downloadTarget, transcriptFileName } from './transcriptVersions';

describe('transcriptFileName：下載的檔名', () => {
  it('校正後版本沿用音檔的檔名，只換副檔名', () => {
    expect(transcriptFileName('會議.mp3', 'srt', 'corrected')).toBe('會議.srt');
  });

  it('原始轉錄多一段 .original，和校正後版本放在同一個資料夾不會搞混', () => {
    expect(transcriptFileName('會議.mp3', 'srt', 'original')).toBe('會議.original.srt');
    expect(transcriptFileName('2026.10.20 會議.m4a', 'txt', 'original')).toBe('2026.10.20 會議.original.txt');
  });
});

describe('downloadMenuItems：History 一列的下載選單', () => {
  const labels = (items) => items.map((item) => item.label);

  it('沒有校正的任務和以前一樣，只有四種輸出格式', () => {
    const items = downloadMenuItems(false);

    expect(labels(items)).toEqual(['LRC', 'SRT', 'VTT', 'TXT']);
    expect(items.map((item) => downloadTarget(item.key)))
      .toEqual(['lrc', 'srt', 'vtt', 'txt'].map((format) => ({ format, version: 'corrected' })));
  });

  it('有校正的任務分兩組：校正後版本在前，原始轉錄另外一組，兩組都有四種輸出格式', () => {
    const [corrected, original] = downloadMenuItems(true);

    expect([corrected.label, original.label]).toEqual(['校正後版本', '原始轉錄']);
    expect(corrected.children.map((item) => downloadTarget(item.key)))
      .toEqual(['lrc', 'srt', 'vtt', 'txt'].map((format) => ({ format, version: 'corrected' })));
    expect(original.children.map((item) => downloadTarget(item.key)))
      .toEqual(['lrc', 'srt', 'vtt', 'txt'].map((format) => ({ format, version: 'original' })));
    expect(labels(original.children)).toEqual(labels(corrected.children));
  });
});
