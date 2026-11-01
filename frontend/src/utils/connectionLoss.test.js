import { describe, expect, it } from 'vitest';
import { CONNECTION, connectionLost, describeConnection } from './connectionLoss.js';
import { applyFileResult } from './fileResult.js';

// 排隊中之後連線斷了的檔案卡：任務已經派送，記下了它的 task_uuid
const queued = {
  uid: 'f1',
  name: 'meeting.wav',
  status: 'processing',
  statusText: '排隊中，輪到時開始轉錄...',
  task_uuid: 'task-1',
  sessionId: 'session-1',
};

describe('送出任務之後連線斷了：檔案卡記下連線的狀況（#280）', () => {
  it('任務本身仍是處理中，狀態文字也不動：任務可能還在伺服器上跑', () => {
    expect(connectionLost(queued, CONNECTION.LOST)).toEqual({ ...queued, connection: 'lost' });
    expect(connectionLost(queued, CONNECTION.UNREACHABLE)).toEqual({ ...queued, connection: 'unreachable' });
  });

  it('正在重新連線：寫出連線中斷，說任務沒有停、不必重新轉錄', () => {
    const shown = describeConnection(CONNECTION.LOST);
    expect(shown.label).toBe('連線中斷，正在重新連線...');
    expect(shown.reason).toBe('和伺服器的連線中斷了');
    expect(shown.nextStep).toContain('不必重新轉錄');
    expect(shown.links).toEqual([]);
  });

  it('連不上伺服器：請使用者重新開啟 Mimiji，也可以到任務頁或歷史紀錄查看', () => {
    const shown = describeConnection(CONNECTION.UNREACHABLE);
    expect(shown.label).toBe('連線中斷，連不上伺服器');
    expect(shown.reason).toBe('連不上伺服器，Mimiji 可能已經關閉');
    expect(shown.nextStep).toContain('重新開啟 Mimiji');
    expect(shown.links).toEqual([
      { label: '任務頁', to: '/tasks' },
      { label: '歷史紀錄', to: '/history' },
    ]);
  });

  it('沒有記號或認不得的狀況：不顯示', () => {
    expect(describeConnection(null)).toBeNull();
    expect(describeConnection(undefined)).toBeNull();
    expect(describeConnection('offline')).toBeNull();
  });
});

describe('接回之後收到任務的狀態：清掉連線中斷的記號', () => {
  const lost = connectionLost(queued, CONNECTION.UNREACHABLE);

  it('任務還在跑：接著顯示進度', () => {
    const card = applyFileResult(lost, { status_code: 'PROCESSING', status_text: '轉錄中...', task_uuid: 'task-1' });
    expect(card).toMatchObject({ status: 'processing', statusText: '轉錄中...' });
    expect(card).not.toHaveProperty('connection');
  });

  it('斷線期間任務完成了：顯示結果', () => {
    const card = applyFileResult(lost, {
      status_code: 'COMPLETED',
      status_text: '任務完成',
      task_uuid: 'task-1',
      result: { transcripts: { txt: '[S0]你好' } },
    });
    expect(card).toMatchObject({ status: 'completed', result: { txt: '[S0]你好' } });
    expect(card).not.toHaveProperty('connection');
  });

  it('伺服器上已經沒有這個任務（例如還沒做完就重新啟動了）：顯示失敗與錯誤碼', () => {
    const card = applyFileResult(lost, {
      status_code: 'FAILED',
      status_text: '任務失敗: 伺服器上已經沒有這個任務',
      task_uuid: 'task-1',
      error_code: 'INTERRUPTED',
      error_message: '伺服器上已經沒有這個任務',
    });
    expect(card).toMatchObject({
      status: 'error',
      failure: { code: 'INTERRUPTED', detail: '伺服器上已經沒有這個任務' },
    });
    expect(card).not.toHaveProperty('connection');
  });
});
