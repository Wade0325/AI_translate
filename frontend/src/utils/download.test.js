import { describe, it, expect } from 'vitest';
import { renameExtension, uniqueFileNames } from './download';

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

describe('uniqueFileNames：打包進同一個 ZIP 的檔名彼此不撞名，解壓縮時不會互相覆蓋', () => {
  it('沒有撞名時和單檔下載的檔名一樣', () => {
    expect(uniqueFileNames(['interview.mp3', 'meeting.wav'], 'srt')).toEqual(['interview.srt', 'meeting.srt']);
  });

  it('主檔名相同、副檔名不同時保留原本的副檔名，看得出是哪個音檔的', () => {
    expect(uniqueFileNames(['a.mp3', 'b.wav', 'a.wav'], 'srt')).toEqual(['a.mp3.srt', 'b.srt', 'a.wav.srt']);
  });

  it('同一個檔名上傳兩次時照 Windows 的寫法加編號', () => {
    expect(uniqueFileNames(['a.mp3', 'a.mp3', 'a.mp3'], 'txt')).toEqual(['a.txt', 'a (2).txt', 'a (3).txt']);
  });

  it('不分大小寫：Windows 上 A.srt 與 a.srt 是同一個檔', () => {
    expect(uniqueFileNames(['A.MP3', 'a.wav'], 'srt')).toEqual(['A.MP3.srt', 'a.wav.srt']);
    expect(uniqueFileNames(['Talk.wav', 'talk.WAV'], 'vtt')).toEqual(['Talk.vtt', 'talk (2).vtt']);
  });

  it('保留副檔名之後撞上別的檔案時，再加編號', () => {
    expect(uniqueFileNames(['a.mp3', 'a.wav', 'a.mp3.m4a'], 'lrc'))
      .toEqual(['a.mp3.lrc', 'a.wav.lrc', 'a.mp3 (2).lrc']);
  });

  it('同名和不同副檔名混在一起時，每個檔名都只出現一次', () => {
    const names = uniqueFileNames(['a.mp3', 'a.wav', 'a.mp3', 'a', 'A.WAV'], 'srt');
    expect(names).toEqual(['a.mp3.srt', 'a.wav.srt', 'a.mp3 (2).srt', 'a.srt', 'A.WAV (2).srt']);
    expect(new Set(names.map((n) => n.toLowerCase())).size).toBe(names.length);
  });
});
