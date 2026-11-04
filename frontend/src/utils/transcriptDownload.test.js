import { describe, expect, it } from 'vitest';
import { planFileDownload, planZipDownload } from './transcriptDownload';

const TRANSCRIPTS = { lrc: '[00:00.000]一\n', srt: '1\n00:00:00,000 --> 00:00:01,000\n一\n', vtt: 'WEBVTT\n', txt: '一\n' };

// 檔案卡上已完成的檔案：單檔任務完成時帶四種輸出格式
const done = (name, result = TRANSCRIPTS) => ({ name, status: 'completed', result });
// 批次模式完成的檔案：結果存在後端，檔案卡上沒有 result
const batchDone = (name) => ({ name, status: 'completed', statusText: '批次結果已儲存，可在 History 頁面下載' });

describe('planFileDownload：下載一個檔案的一種輸出格式', () => {
  it('檔名沿用音檔的檔名，內容是那種格式的轉錄結果', () => {
    expect(planFileDownload(done('meeting.wav'), 'srt')).toEqual({
      download: { fileName: 'meeting.srt', content: TRANSCRIPTS.srt },
      notice: null,
    });
  });

  it('沒有轉錄結果（批次模式完成）時不下載，請使用者到 History 頁面下載，不存出內容是 undefined 的檔', () => {
    expect(planFileDownload(batchDone('meeting.wav'), 'srt')).toEqual({
      download: null,
      notice: { type: 'warning', content: 'meeting.wav 的轉錄結果請到 History 頁面下載' },
    });
    expect(planFileDownload({ name: 'meeting.wav', result: null }, 'txt').download).toBeNull();
  });

  it('這種格式沒有內容時不下載空檔，說明哪個檔案沒有哪種格式', () => {
    expect(planFileDownload(done('meeting.wav', { ...TRANSCRIPTS, vtt: '' }), 'vtt')).toEqual({
      download: null,
      notice: { type: 'warning', content: 'meeting.wav 沒有 VTT 內容' },
    });
  });
});

describe('planZipDownload：把同一種輸出格式打包成一個 ZIP', () => {
  const NOW = new Date(2026, 9, 31, 7, 30);

  it('每個檔案一個項目；主檔名相同的音檔不會互相覆蓋', () => {
    const plan = planZipDownload([done('a.mp3'), done('a.wav'), done('b.m4a')], 'srt', NOW);

    expect(plan.entries).toEqual([
      { fileName: 'a.mp3.srt', content: TRANSCRIPTS.srt },
      { fileName: 'a.wav.srt', content: TRANSCRIPTS.srt },
      { fileName: 'b.srt', content: TRANSCRIPTS.srt },
    ]);
    expect(plan.notice).toEqual({ type: 'success', content: '已下載 3 個 SRT 檔的壓縮包' });
  });

  it('ZIP 檔名的日期是本地日期：台灣早上 8 點前不會變成前一天', () => {
    // 2026-10-31 07:30（台北）是 UTC 的 2026-10-30 23:30
    expect(planZipDownload([done('a.mp3')], 'lrc', NOW).zipFileName).toBe('transcripts_LRC_2026-10-31.zip');
  });

  it('沒有內容的檔案不打包，訊息只算實際打包的檔案，並說明哪些沒打包、為什麼', () => {
    const files = [done('a.wav'), done('b.wav', { ...TRANSCRIPTS, srt: '' }), batchDone('c.wav'), done('d.wav')];
    const plan = planZipDownload(files, 'srt', NOW);

    expect(plan.entries.map((e) => e.fileName)).toEqual(['a.srt', 'd.srt']);
    expect(plan.notice).toEqual({
      type: 'warning',
      content: '已下載 2 個 SRT 檔的壓縮包；b.wav 沒有 SRT 內容；c.wav 的轉錄結果請到 History 頁面下載',
    });
  });

  it('沒有任何檔案拿得到內容時沒有項目（不產生空的 ZIP），說明原因', () => {
    const plan = planZipDownload([batchDone('a.wav'), batchDone('b.wav')], 'txt', NOW);

    expect(plan.entries).toEqual([]);
    expect(plan.notice).toEqual({
      type: 'warning',
      content: '沒有可以下載的 TXT 內容：a.wav、b.wav 的轉錄結果請到 History 頁面下載',
    });
  });

  it('沒打包的檔案很多時只列前三個檔名', () => {
    const files = [done('ok.wav'), ...['1', '2', '3', '4', '5'].map((n) => batchDone(`${n}.wav`))];

    expect(planZipDownload(files, 'vtt', NOW).notice.content)
      .toBe('已下載 1 個 VTT 檔的壓縮包；1.wav、2.wav、3.wav 等 5 個檔案的轉錄結果請到 History 頁面下載');
  });
});
