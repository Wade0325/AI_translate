import { describe, expect, it } from 'vitest';
import { cancelFile } from './cancelOutcome.js';

// 假的後端 API：取消端點回 cancelled；任務紀錄與輸出格式只回給的那些，其他的像後端一樣丟錯（404）
function fakeApi({ cancelled, records = [], transcripts = {} }) {
  const notFound = () => {
    throw new Error('找不到此任務紀錄');
  };
  return {
    transcription: { cancel: async () => cancelled },
    history: {
      get: async (taskUuid) => records.find((r) => r.task_uuid === taskUuid) ?? notFound(),
      downloadTranscript: async (taskUuid, fmt) => transcripts[taskUuid]?.[fmt] ?? notFound(),
    },
  };
}

// 取消端點沒有取消時的回應：只留測試用得到的欄位
const notCancelled = (reason) => ({ cancelled: false, reason });

// 還在上傳、還沒收到任何狀態訊息的檔案卡
const uploading = { name: 'a.wav', status: 'processing', sessionId: 'session-2' };

// 停在處理中的檔案卡：這次送出（session-2）的任務已經廣播過狀態，檔案記下了它的 task_uuid，
// 結果卻沒送到畫面（例如 WebSocket 斷了）
const stuck = { ...uploading, task_uuid: 'task-2', model: 'gemini-3.5-flash' };

// 任務紀錄（GET /history/{task_uuid}）：只留用得到的欄位
const recordOf = (status, fields = {}) => ({
  task_uuid: 'task-2',
  session_id: 'session-2',
  status,
  ...fields,
});

// 沒有取消時，檔案卡從「正在取消...」改回處理中
const stillProcessing = { statusText: '處理中...' };

describe('按取消之後', () => {
  it('取消了：說取消了哪個檔案的任務，檔案卡等後端宣告已取消', async () => {
    expect(await cancelFile(uploading, fakeApi({ cancelled: { cancelled: true } }))).toEqual({
      notice: { type: 'info', content: '已取消任務：a.wav' },
      patch: null,
    });
  });

  it('任務已經結束（完成或失敗，或正在收尾）：說來不及取消，不叫使用者再等', async () => {
    expect(await cancelFile(uploading, fakeApi({ cancelled: notCancelled('finished') }))).toEqual({
      notice: { type: 'info', content: '任務已經結束，無法取消。' },
      patch: stillProcessing,
    });
  });

  it('任務還沒提交到佇列（可能還在上傳）：請使用者稍後再按一次', async () => {
    expect(await cancelFile(uploading, fakeApi({ cancelled: notCancelled('not-started') }))).toEqual({
      notice: { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' },
      patch: stillProcessing,
    });
  });

  it('沒有取消、原因又認不得（沒帶、後端多了新的原因，或回應沒有內容）：只說沒有取消，不猜原因', async () => {
    for (const response of [notCancelled(undefined), notCancelled('busy'), null]) {
      expect(await cancelFile(uploading, fakeApi({ cancelled: response }))).toEqual({
        notice: { type: 'warning', content: '任務沒有取消。' },
        patch: stillProcessing,
      });
    }
  });
});

describe('檔案卡停在處理中、任務其實已經結束時按取消：照任務紀錄顯示真正的結果（#186）', () => {
  it('任務已經失敗：檔案卡改成失敗，顯示失敗原因，不叫使用者稍後再試', async () => {
    const api = fakeApi({
      cancelled: notCancelled('not-started'),
      records: [recordOf('FAILED', { error_message: '模型壞掉了' })],
    });

    expect(await cancelFile(stuck, api)).toEqual({
      notice: { type: 'info', content: '任務已經失敗，無法取消：a.wav' },
      patch: {
        status: 'error',
        percent: 100,
        statusText: '任務失敗: 模型壞掉了',
        error: '任務失敗: 模型壞掉了',
      },
    });
  });

  it('任務已經完成：檔案卡改成完成，取回輸出格式，檔案卡可以預覽與下載', async () => {
    const api = fakeApi({
      cancelled: notCancelled('not-started'),
      records: [recordOf('COMPLETED', {
        total_tokens: 1200,
        cost: 0.0034,
        audio_duration_seconds: 61.5,
        model_used: 'gemini-3.5-flash',
        source_language: 'zh-TW',
      })],
      transcripts: { 'task-2': { lrc: '[00:00.00]你好', srt: '1\n00:00:00,000 --> 00:00:01,000\n你好', vtt: 'WEBVTT', txt: '你好' } },
    });

    expect(await cancelFile(stuck, api)).toEqual({
      notice: { type: 'info', content: '任務已經完成，無法取消：a.wav' },
      patch: {
        status: 'completed',
        percent: 100,
        statusText: '任務完成',
        result: { lrc: '[00:00.00]你好', srt: '1\n00:00:00,000 --> 00:00:01,000\n你好', vtt: 'WEBVTT', txt: '你好' },
        tokens_used: 1200,
        cost: 0.0034,
        audioDurationSec: 61.5,
        model: 'gemini-3.5-flash',
        sourceLanguage: 'zh-TW',
      },
    });
  });

  it('任務已經完成、有的輸出格式產生不出內容（後端回 404）：那一種當成空的，和完成時的廣播一樣', async () => {
    const api = fakeApi({
      cancelled: notCancelled('not-started'),
      records: [recordOf('COMPLETED')],
      transcripts: { 'task-2': { lrc: '[00:00.00]你好', srt: '1', txt: '你好' } },
    });

    const { patch } = await cancelFile(stuck, api);

    expect(patch.result).toEqual({ lrc: '[00:00.00]你好', srt: '1', vtt: '', txt: '你好' });
  });

  it('任務已經完成、輸出格式卻取不回來：檔案卡照樣改成完成，請使用者到 History 頁面下載', async () => {
    const api = fakeApi({ cancelled: notCancelled('not-started'), records: [recordOf('COMPLETED')] });

    const { patch } = await cancelFile(stuck, api);

    expect(patch).toMatchObject({
      status: 'completed',
      statusText: '任務完成，結果請到 History 頁面下載',
      result: null,
    });
  });

  it('任務已經取消（上次按取消成功了，已取消的廣播卻沒送到畫面）：檔案卡改成已取消', async () => {
    const api = fakeApi({ cancelled: notCancelled('not-started'), records: [recordOf('CANCELLED')] });

    expect(await cancelFile(stuck, api)).toEqual({
      notice: { type: 'info', content: '任務已經取消：a.wav' },
      patch: { status: 'cancelled', percent: 100, statusText: '任務已取消' },
    });
  });

  it('任務結束時登記沒清掉（取消端點第一次按回 finished）：一樣照任務紀錄改檔案卡', async () => {
    const api = fakeApi({ cancelled: notCancelled('finished'), records: [recordOf('CANCELLED')] });

    expect((await cancelFile(stuck, api)).patch).toMatchObject({ status: 'cancelled' });
  });

  it('失敗後重新轉錄、新的音檔還在上傳時按取消：不拿同一個檔案上一個任務的結果回答', async () => {
    // 上一次送出（session-1）的任務失敗了，檔案上還留著它的 task_uuid
    const reTranscribing = { ...uploading, task_uuid: 'task-1' };
    const api = fakeApi({
      cancelled: notCancelled('not-started'),
      records: [{ task_uuid: 'task-1', session_id: 'session-1', status: 'FAILED', error_message: '模型壞掉了' }],
    });

    expect(await cancelFile(reTranscribing, api)).toEqual({
      notice: { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' },
      patch: stillProcessing,
    });
  });

  it('任務紀錄還在處理中，或查不到（例如已經在 History 頁面刪掉）：照取消端點的原因說，檔案卡不動', async () => {
    for (const records of [[recordOf('PROCESSING')], []]) {
      const api = fakeApi({ cancelled: notCancelled('not-started'), records });

      expect(await cancelFile(stuck, api)).toEqual({
        notice: { type: 'warning', content: '任務尚未提交到佇列（可能還在上傳），請稍後再試。' },
        patch: stillProcessing,
      });
    }
  });
});
