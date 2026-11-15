import { describe, expect, it } from 'vitest';
import { ApiError } from '../services/api';
import { fetchTranscripts, planFileDownload, planZipDownload } from './transcriptDownload';

const SRT = '1\n00:00:00,000 --> 00:00:01,000\n校正後\n';

/**
 * 假的後端 API：下載端點回 contents[task_uuid][fmt]；任務紀錄只有 records 裡的。其他的像後端一樣回錯誤：
 * 下載端點對沒有紀錄的任務、產生不出內容的格式都回 404，任務紀錄查不到時也是 404。failing 裡的任務
 * 連不上（不是 HTTP 錯誤）。下載的請求記在 calls。
 */
function fakeApi({ contents = {}, records = Object.keys(contents), failing = [] } = {}) {
  const calls = [];
  const notFound = (detail) => {
    throw new ApiError(404, detail);
  };
  return {
    calls,
    history: {
      get: async (taskUuid) => (records.includes(taskUuid) ? { task_uuid: taskUuid } : notFound('找不到此任務紀錄')),
      downloadTranscript: async (taskUuid, fmt, options) => {
        calls.push({ taskUuid, fmt, ...options });
        if (failing.includes(taskUuid)) throw new TypeError('Failed to fetch');
        if (!records.includes(taskUuid)) return notFound('找不到此任務紀錄');
        return contents[taskUuid]?.[fmt] || notFound('無法產生此格式的字幕內容');
      },
    },
  };
}

// 檔案卡上已完成的檔案：單檔任務完成時，狀態訊息帶著任務紀錄的 id
const done = (name, taskUuid) => ({ name, status: 'completed', task_uuid: taskUuid });
// 批次模式完成的檔案：轉錄頁只知道批次結束了，不知道每個檔案的任務紀錄
const batchDone = (name) => ({ name, status: 'completed', statusText: '批次結果已儲存，可在 History 頁面下載' });

describe('fetchTranscripts：向下載端點拿校正後版本', () => {
  it('每個檔案向它的任務紀錄拿那種格式的校正後版本', async () => {
    const api = fakeApi({ contents: { 'task-a': { srt: SRT }, 'task-b': { srt: 'B' } } });

    const fetched = await fetchTranscripts([done('a.wav', 'task-a'), done('b.wav', 'task-b')], 'srt', api);

    expect(fetched.map((f) => f.content)).toEqual([SRT, 'B']);
    expect(api.calls).toEqual([
      { taskUuid: 'task-a', fmt: 'srt', version: 'corrected' },
      { taskUuid: 'task-b', fmt: 'srt', version: 'corrected' },
    ]);
  });

  it('不用完成時送到畫面的內容：之後的校正才拿得到', async () => {
    const file = { ...done('a.wav', 'task-a'), result: { srt: '完成時的內容' } };

    const [fetched] = await fetchTranscripts([file], 'srt', fakeApi({ contents: { 'task-a': { srt: SRT } } }));

    expect(fetched.content).toBe(SRT);
  });

  it('沒有任務紀錄的 id（批次模式完成）時不打下載端點', async () => {
    const api = fakeApi();

    const [fetched] = await fetchTranscripts([batchDone('a.wav')], 'srt', api);

    expect(fetched.missing).toBe('no-task');
    expect(api.calls).toEqual([]);
  });

  it('任務紀錄還在、這種格式產生不出內容時，是沒有內容', async () => {
    const api = fakeApi({ contents: { 'task-a': { srt: SRT } } });

    const [fetched] = await fetchTranscripts([done('a.wav', 'task-a')], 'vtt', api);

    expect(fetched.missing).toBe('empty');
  });

  it('任務紀錄已經被刪掉時，分得出是被刪掉了', async () => {
    const [fetched] = await fetchTranscripts([done('a.wav', 'task-a')], 'srt', fakeApi({ records: [] }));

    expect(fetched.missing).toBe('deleted');
  });

  it('連不上伺服器時是下載失敗，不當成沒有內容', async () => {
    const api = fakeApi({ contents: { 'task-a': { srt: SRT } }, failing: ['task-a'] });

    const [fetched] = await fetchTranscripts([done('a.wav', 'task-a')], 'srt', api);

    expect(fetched.missing).toBe('failed');
  });
});

// 下載端點拿到的結果：拿到內容，或拿不到的原因
const got = (name, content = SRT) => ({ file: { name }, content });
const missing = (name, reason) => ({ file: { name }, missing: reason });

describe('planFileDownload：下載一個檔案的一種輸出格式', () => {
  it('檔名沿用音檔的檔名，內容是下載端點給的校正後版本', () => {
    expect(planFileDownload(got('meeting.wav'), 'srt')).toEqual({
      download: { fileName: 'meeting.srt', content: SRT },
      notice: null,
    });
  });

  it('批次模式完成的檔案不下載，請使用者到 History 頁面下載', () => {
    expect(planFileDownload(missing('meeting.wav', 'no-task'), 'srt')).toEqual({
      download: null,
      notice: { type: 'warning', content: 'meeting.wav 的轉錄結果請到 History 頁面下載' },
    });
  });

  it('這種格式沒有內容時不下載空檔，說明哪個檔案沒有哪種格式', () => {
    expect(planFileDownload(missing('meeting.wav', 'empty'), 'vtt')).toEqual({
      download: null,
      notice: { type: 'warning', content: 'meeting.wav 沒有 VTT 內容' },
    });
  });

  it('任務紀錄被刪掉時說明原因', () => {
    expect(planFileDownload(missing('meeting.wav', 'deleted'), 'srt')).toEqual({
      download: null,
      notice: { type: 'warning', content: 'meeting.wav 的任務紀錄已經在 History 刪掉了，下載不到轉錄結果' },
    });
  });

  it('下載失敗時請使用者稍後再試', () => {
    expect(planFileDownload(missing('meeting.wav', 'failed'), 'srt').notice)
      .toEqual({ type: 'warning', content: 'meeting.wav 下載失敗，請稍後再試' });
  });
});

describe('planZipDownload：把同一種輸出格式打包成一個 ZIP', () => {
  const NOW = new Date(2026, 9, 31, 7, 30);

  it('每個檔案一個項目；主檔名相同的音檔不會互相覆蓋', () => {
    const plan = planZipDownload([got('a.mp3', 'A'), got('a.wav', 'B'), got('b.m4a', 'C')], 'srt', NOW);

    expect(plan.entries).toEqual([
      { fileName: 'a.mp3.srt', content: 'A' },
      { fileName: 'a.wav.srt', content: 'B' },
      { fileName: 'b.srt', content: 'C' },
    ]);
    expect(plan.notice).toEqual({ type: 'success', content: '已下載 3 個 SRT 檔的壓縮包' });
  });

  it('ZIP 檔名的日期是本地日期：台灣早上 8 點前不會變成前一天', () => {
    // 2026-10-31 07:30（台北）是 UTC 的 2026-10-30 23:30
    expect(planZipDownload([got('a.mp3')], 'lrc', NOW).zipFileName).toBe('transcripts_LRC_2026-10-31.zip');
  });

  it('拿不到內容的檔案不打包，訊息只算實際打包的檔案，並依原因說明哪些沒打包', () => {
    const fetched = [
      got('a.wav'), missing('b.wav', 'empty'), missing('c.wav', 'no-task'),
      missing('d.wav', 'deleted'), missing('e.wav', 'failed'), got('f.wav'),
    ];
    const plan = planZipDownload(fetched, 'srt', NOW);

    expect(plan.entries.map((e) => e.fileName)).toEqual(['a.srt', 'f.srt']);
    expect(plan.notice).toEqual({
      type: 'warning',
      content: '已下載 2 個 SRT 檔的壓縮包；b.wav 沒有 SRT 內容；c.wav 的轉錄結果請到 History 頁面下載；'
        + 'd.wav 的任務紀錄已經在 History 刪掉了，下載不到轉錄結果；e.wav 下載失敗，請稍後再試',
    });
  });

  it('沒有任何檔案拿得到內容時沒有項目（不產生空的 ZIP），說明原因', () => {
    const plan = planZipDownload([missing('a.wav', 'no-task'), missing('b.wav', 'no-task')], 'txt', NOW);

    expect(plan.entries).toEqual([]);
    expect(plan.notice).toEqual({
      type: 'warning',
      content: '沒有可以下載的 TXT 內容：a.wav、b.wav 的轉錄結果請到 History 頁面下載',
    });
  });

  it('沒打包的檔案很多時只列前三個檔名', () => {
    const fetched = [got('ok.wav'), ...['1', '2', '3', '4', '5'].map((n) => missing(`${n}.wav`, 'deleted'))];

    expect(planZipDownload(fetched, 'vtt', NOW).notice.content)
      .toBe('已下載 1 個 VTT 檔的壓縮包；1.wav、2.wav、3.wav 等 5 個檔案的任務紀錄已經在 History 刪掉了，下載不到轉錄結果');
  });
});
