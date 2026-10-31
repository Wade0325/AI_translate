import { describe, expect, it } from 'vitest';
import { acceptAttribute, formatLabels, maxSizeLabel, rejectionOf } from './uploadLimits.js';

// 形狀照後端 GET /upload/limits（backend/app/core/upload_formats.py）
const LIMITS = {
  formats: [
    { extension: '.mp3', label: 'MP3', kind: 'audio' },
    { extension: '.wav', label: 'WAV', kind: 'audio' },
    { extension: '.mp4', label: 'MP4', kind: 'video' },
    { extension: '.webm', label: 'WebM', kind: 'video' },
  ],
  max_bytes: 2 * 1024 ** 3,
};

// 只用到 name 與 size；type（瀏覽器給的 MIME 類型）刻意不看
const file = (name, size = 1024, type = '') => ({ name, size, type });

describe('上傳格式與大小（#258）', () => {
  it('檔案選擇器列出清單上的副檔名', () => {
    expect(acceptAttribute(LIMITS)).toBe('.mp3,.wav,.mp4,.webm');
  });

  it('說明文字分音檔與影片列出格式，上限寫成 GB', () => {
    expect(formatLabels(LIMITS, 'audio')).toBe('MP3、WAV');
    expect(formatLabels(LIMITS, 'video')).toBe('MP4、WebM');
    expect(maxSizeLabel(LIMITS)).toBe('2 GB');
    expect(maxSizeLabel({ ...LIMITS, max_bytes: 1.5 * 1024 ** 3 })).toBe('1.5 GB');
  });

  it('清單上的格式收，不分大小寫，也不看瀏覽器給的 MIME 類型', () => {
    expect(rejectionOf(file('meeting.mp3', 1024, 'audio/mpeg'), LIMITS)).toBeNull();
    expect(rejectionOf(file('IMG_0001.MP4', 1024, ''), LIMITS)).toBeNull();
    expect(rejectionOf(file('會議.2026.10.31.webm', 1024, 'audio/webm'), LIMITS)).toBeNull();
  });

  it('不在清單上的格式說明不支援，並分音檔與影片列出可以用的格式', () => {
    const reason = '（音檔可以用 MP3、WAV；影片可以用 MP4、WebM）';
    expect(rejectionOf(file('voice.ogg', 1024, 'audio/ogg'), LIMITS)).toBe(`不支援這種格式：voice.ogg${reason}`);
    expect(rejectionOf(file('notes.txt', 1024, 'audio/mpeg'), LIMITS)).toBe(`不支援這種格式：notes.txt${reason}`);
    expect(rejectionOf(file('recording'), LIMITS)).toBe(`不支援這種格式：recording${reason}`);
    expect(rejectionOf(file('.mp3'), LIMITS)).toBe(`不支援這種格式：.mp3${reason}`);
  });

  it('上限以內收，超過的寫出大小與上限；空檔案不收', () => {
    // 2 小時、48 kHz 立體聲 24-bit 的 WAV 約 2.07 GB（1.93 GiB）
    expect(rejectionOf(file('long.wav', 7200 * 48000 * 2 * 3 + 44), LIMITS)).toBeNull();
    expect(rejectionOf(file('long.wav', LIMITS.max_bytes), LIMITS)).toBeNull();
    expect(rejectionOf(file('long.wav', 2.5 * 1024 ** 3), LIMITS)).toBe('檔案太大：long.wav（2.5 GB，上限 2 GB）');
    expect(rejectionOf(file('empty.mp3', 0), LIMITS)).toBe('檔案是空的：empty.mp3');
  });
});
