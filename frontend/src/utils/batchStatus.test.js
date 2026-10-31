import { describe, expect, it } from 'vitest';
import { batchCardChange, batchWatch } from './batchStatus.js';
import { CONNECTION, connectionLost } from './connectionLoss.js';

// 一批兩個檔案，送出之後連線斷了、正在重新連線：檔案卡還在處理中，記著連線中斷
const card = (uid) =>
  connectionLost(
    { uid, name: `${uid}.wav`, status: 'processing', statusText: '前處理與上傳 (1/2)', sessionId: 'session-1' },
    CONNECTION.LOST,
  );

describe('批次的狀態訊息怎麼改這一批還在等的檔案卡（#286）', () => {
  it('送出給供應商了：改成批次等待，清掉連線中斷的記號', () => {
    const change = batchCardChange({ status_code: 'BATCH_SUBMITTED', status_text: '批次已送出，等待處理中...' });
    const next = change(card('a'));
    expect(next).toMatchObject({ status: 'batch_pending', statusText: '批次已送出，等待處理中...' });
    expect(next).not.toHaveProperty('connection');
  });

  it('批次層級的進度：狀態文字改成它，清掉連線中斷的記號', () => {
    const change = batchCardChange({ status_code: 'PROCESSING', status_text: '重新連上了，批次還在處理中...' });
    const next = change(card('a'));
    expect(next).toMatchObject({ status: 'processing', statusText: '重新連上了，批次還在處理中...' });
    expect(next).not.toHaveProperty('connection');
  });

  it('檔案層級的：只改那個檔案', () => {
    const change = batchCardChange({
      status_code: 'FAILED', status_text: '任務失敗: 上傳時服務停止了，批次沒有送出', file_uid: 'a', task_uuid: 't-a',
      error_code: 'INTERRUPTED', error_message: '上傳時服務停止了，批次沒有送出',
    });
    expect(change(card('a'))).toMatchObject({
      status: 'error', failure: { code: 'INTERRUPTED', detail: '上傳時服務停止了，批次沒有送出' },
    });
    expect(change(card('a'))).not.toHaveProperty('connection');
    expect(change(card('b'))).toEqual(card('b'));
  });

  it('批次層級的失敗（伺服器上沒有這個批次）：每張都標成沒有送出的失敗，不會當成已經送出', () => {
    const change = batchCardChange({
      status_code: 'FAILED', status_text: '批次沒有送出: 伺服器上沒有這個批次',
      error_code: 'SUBMIT_FAILED', error_message: '伺服器上沒有這個批次',
    });
    for (const uid of ['a', 'b']) {
      const next = change(card(uid));
      expect(next).toMatchObject({ status: 'error', failure: { code: 'SUBMIT_FAILED' } });
      expect(next.status).not.toBe('batch_pending');
    }
  });

  it('批次結束：每個檔案的結果已經各自送過了，不改', () => {
    expect(batchCardChange({ status_code: 'BATCH_COMPLETED', status_text: '批次結束' })).toBeNull();
  });
});

describe('這一批還有沒有檔案在等伺服器的消息', () => {
  it('還沒收到任何消息：每個檔案都在等，連線斷了要接回', () => {
    expect(batchWatch(['a', 'b']).waiting).toBe(true);
  });

  it('進度不會讓檔案結束；每個檔案都結束了才不必再等', () => {
    const watch = batchWatch(['a', 'b']);
    watch.heard({ status_code: 'PROCESSING', status_text: '正在初始化批次 (2 個檔案)...' });
    watch.heard({ status_code: 'PROCESSING', status_text: '前處理與上傳 (1/2)', file_uid: 'a' });
    watch.heard({ status_code: 'FAILED', status_text: '任務失敗', file_uid: 'a' });
    expect(watch.waiting).toBe(true);
    watch.heard({ status_code: 'COMPLETED', status_text: '任務完成', file_uid: 'b' });
    expect(watch.waiting).toBe(false);
  });

  it('送出給供應商之後：結果到任務頁取回，不必再等', () => {
    const watch = batchWatch(['a', 'b']);
    watch.heard({ status_code: 'BATCH_SUBMITTED', status_text: '批次已送出' });
    expect(watch.waiting).toBe(false);
  });

  it('整批沒有送出（批次層級的失敗）：不必再等', () => {
    const watch = batchWatch(['a', 'b']);
    watch.heard({ status_code: 'FAILED', status_text: '提交任務失敗', error_code: 'SUBMIT_FAILED' });
    expect(watch.waiting).toBe(false);
  });
});
