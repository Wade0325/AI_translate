import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { createMemoryStorage } from '../test/memoryStorage';
import { registerTranscribeSession } from './transcribeSessions';
import {
  batchDisplayStatus,
  buildTaskSessions,
  isBatchCompleted,
  isBatchFailed,
  isBatchInterrupted,
  isBatchProcessing,
  isSingleCompleted,
  isSingleProcessing,
  sessionHasProcessing,
} from './taskSessions';

// 後端 GET /batch/tasks 的一筆批次，只留分組用得到的欄位
function batch(fields) {
  return { batch_id: 'batch-1', status: 'POLLING', created_at: '2026-10-20T10:00:00', ...fields };
}

// 後端 GET /history/active 的一筆單檔任務，只留分組用得到的欄位
function single(fields) {
  return {
    task_uuid: 'task-1',
    status: 'PROCESSING',
    model_used: 'moss-align',
    request_timestamp: '2026-10-20T10:00:00',
    ...fields,
  };
}

// 每一組裡的任務，批次用 batch id、單檔任務用 uuid 表示
function groups(sessions) {
  return sessions.map((session) => session.items.map(({ task }) => task.batch_id ?? task.task_uuid));
}

// 單檔任務查不到 session id 時，會改查這個分頁記下的紀錄（transcribeSessions.js）
beforeEach(() => {
  vi.stubGlobal('sessionStorage', createMemoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('buildTaskSessions：任務頁把同一次開始的任務分成一組', () => {
  it('沒有任務時沒有分組', () => {
    expect(buildTaskSessions()).toEqual([]);
  });

  it('同一次開始的批次與單檔任務分在同一組', () => {
    const sessions = buildTaskSessions(
      [batch({ batch_id: 'batch-1', session_id: 'session-1' })],
      [single({ task_uuid: 'task-1', session_id: 'session-1' })],
    );
    expect(groups(sessions)).toEqual([['batch-1', 'task-1']]);
  });

  it('沒有 session id 的批次各自一組', () => {
    const sessions = buildTaskSessions(
      [
        batch({ batch_id: 'batch-1', created_at: '2026-10-20T10:00:00' }),
        batch({ batch_id: 'batch-2', created_at: '2026-10-20T09:00:00' }),
      ],
      [],
    );
    expect(groups(sessions)).toEqual([['batch-1'], ['batch-2']]);
  });

  it('單檔任務還沒寫入 session id 時，用這個分頁記下的那次開始分組', () => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a'] });
    const sessions = buildTaskSessions(
      [batch({ batch_id: 'batch-1', session_id: 'session-1' })],
      [single({ task_uuid: 'task-1', file_uid: 'file-a' })],
    );
    expect(groups(sessions)).toEqual([['batch-1', 'task-1']]);
  });

  describe('查不到是哪一次開始的單檔任務，用送出時間與模型推測', () => {
    it('同一個模型、相隔剛好 10 分鐘，併成一組', () => {
      const sessions = buildTaskSessions([], [
        single({ task_uuid: 'task-1', request_timestamp: '2026-10-20T10:00:00' }),
        single({ task_uuid: 'task-2', request_timestamp: '2026-10-20T10:10:00' }),
      ]);
      expect(groups(sessions)).toEqual([['task-1', 'task-2']]);
    });

    it('相隔超過 10 分鐘就分成兩組，新的在前', () => {
      const sessions = buildTaskSessions([], [
        single({ task_uuid: 'task-1', request_timestamp: '2026-10-20T10:00:00' }),
        single({ task_uuid: 'task-2', request_timestamp: '2026-10-20T10:10:01' }),
      ]);
      expect(groups(sessions)).toEqual([['task-2'], ['task-1']]);
    });

    it('10 分鐘從同一組最後一個任務算起', () => {
      const sessions = buildTaskSessions([], [
        single({ task_uuid: 'task-1', request_timestamp: '2026-10-20T10:00:00' }),
        single({ task_uuid: 'task-2', request_timestamp: '2026-10-20T10:08:00' }),
        single({ task_uuid: 'task-3', request_timestamp: '2026-10-20T10:16:00' }),
      ]);
      expect(groups(sessions)).toEqual([['task-1', 'task-2', 'task-3']]);
    });

    it('模型不同就分成兩組', () => {
      const sessions = buildTaskSessions([], [
        single({ task_uuid: 'task-1', model_used: 'moss-align', request_timestamp: '2026-10-20T10:00:00' }),
        single({ task_uuid: 'task-2', model_used: 'gemini-3.5-flash', request_timestamp: '2026-10-20T10:01:00' }),
      ]);
      expect(groups(sessions)).toEqual([['task-2'], ['task-1']]);
    });

    it('沒有任何時間的任務各自一組', () => {
      const sessions = buildTaskSessions([], [
        single({ task_uuid: 'task-1', request_timestamp: null }),
        single({ task_uuid: 'task-2', request_timestamp: null }),
      ]);
      expect(groups(sessions)).toEqual([['task-1'], ['task-2']]);
    });

    it('時間無法解析的任務當成沒有時間：自己一組，排在最後', () => {
      const sessions = buildTaskSessions([], [
        single({ task_uuid: 'task-1', request_timestamp: 'not a date' }),
        single({ task_uuid: 'task-2', request_timestamp: '2026-10-20T10:00:00' }),
        single({ task_uuid: 'task-3', request_timestamp: '2026-10-20T10:01:00' }),
      ]);
      expect(groups(sessions)).toEqual([['task-2', 'task-3'], ['task-1']]);
    });
  });

  it('每組的開始時間取組裡最早的時間', () => {
    const [session] = buildTaskSessions(
      [batch({ session_id: 'session-1', created_at: '2026-10-20T10:05:00' })],
      [single({ session_id: 'session-1', request_timestamp: '2026-10-20T10:00:00' })],
    );
    expect(session.startedAt).toBe('2026-10-20T10:00:00');
  });

  it('單檔任務沒有送出時間時，改用完成時間', () => {
    const [session] = buildTaskSessions([], [
      single({ session_id: 'session-1', request_timestamp: null, completed_at: '2026-10-20T10:30:00' }),
    ]);
    expect(session.startedAt).toBe('2026-10-20T10:30:00');
  });

  it('最新的一組排最前面，沒有時間的排最後', () => {
    const sessions = buildTaskSessions(
      [
        batch({ batch_id: 'batch-old', created_at: '2026-10-20T09:00:00' }),
        batch({ batch_id: 'batch-none', created_at: null }),
        batch({ batch_id: 'batch-new', created_at: '2026-10-20T11:00:00' }),
      ],
      [],
    );
    expect(groups(sessions)).toEqual([['batch-new'], ['batch-old'], ['batch-none']]);
  });

  it('檔案數：批次算它的檔案數，單檔任務一個算一個', () => {
    const [session] = buildTaskSessions(
      [
        batch({ batch_id: 'batch-1', session_id: 'session-1', file_count: 3 }),
        batch({ batch_id: 'batch-2', session_id: 'session-1', files: [{}, {}] }),
      ],
      [single({ session_id: 'session-1' })],
    );
    expect(session.fileCount).toBe(6);
  });

  it('批次沒有檔案數也沒有檔案清單時算 0 個', () => {
    const [session] = buildTaskSessions([batch({ session_id: 'session-1' })], []);
    expect(session.fileCount).toBe(0);
  });
});

describe('批次還在處理、停住了、已經完成，或失敗了', () => {
  // 依序是 isBatchProcessing、isBatchInterrupted、isBatchCompleted、isBatchFailed
  const kinds = (task) =>
    [isBatchProcessing, isBatchInterrupted, isBatchCompleted, isBatchFailed].map((is) => is(task));

  it.each(['UPLOADING', 'POLLING', 'RECOVERING'])('%s、看著它的任務還在（或查不出來）是還在處理', (status) => {
    for (const isAlive of [true, null, undefined]) {
      expect(kinds({ status, is_alive: isAlive })).toEqual([true, false, false, false]);
    }
  });

  it.each(['UPLOADING', 'POLLING', 'RECOVERING'])('%s、看著它的任務不在了是停住了', (status) => {
    expect(kinds({ status, is_alive: false })).toEqual([false, true, false, false]);
  });

  it.each(['COMPLETED', 'RETRIEVED'])('%s 是已經完成', (status) => {
    expect(kinds({ status })).toEqual([false, false, true, false]);
  });

  it('FAILED 是失敗了', () => {
    expect(kinds({ status: 'FAILED' })).toEqual([false, false, false, true]);
  });
});

describe('batchDisplayStatus：任務卡片顯示的狀態', () => {
  it('停住的批次：上傳中的是上傳中斷，輪詢中、復原中的是已中斷', () => {
    expect(['UPLOADING', 'POLLING', 'RECOVERING'].map((status) => batchDisplayStatus({ status, is_alive: false })))
      .toEqual(['UPLOADING_DEAD', 'INTERRUPTED', 'INTERRUPTED']);
  });

  it.each(['UPLOADING', 'POLLING', 'RECOVERING', 'COMPLETED', 'RETRIEVED', 'FAILED'])('其他的照批次的狀態：%s', (status) => {
    expect(batchDisplayStatus({ status, is_alive: status === 'FAILED' ? null : true })).toBe(status);
  });
});

describe('isSingleProcessing／isSingleCompleted：單檔任務還在處理，或已經結束', () => {
  it('PROCESSING 是還在處理', () => {
    expect([isSingleProcessing({ status: 'PROCESSING' }), isSingleCompleted({ status: 'PROCESSING' })])
      .toEqual([true, false]);
  });

  it.each(['COMPLETED', 'FAILED'])('%s 是已經結束', (status) => {
    expect([isSingleProcessing({ status }), isSingleCompleted({ status })]).toEqual([false, true]);
  });

  it('CANCELLED 兩者都不是', () => {
    expect([isSingleProcessing({ status: 'CANCELLED' }), isSingleCompleted({ status: 'CANCELLED' })])
      .toEqual([false, false]);
  });
});

describe('sessionHasProcessing：一組裡還有沒有在處理的任務', () => {
  it('有批次還在處理', () => {
    const [session] = buildTaskSessions(
      [batch({ session_id: 'session-1', status: 'POLLING' })],
      [single({ session_id: 'session-1', status: 'COMPLETED' })],
    );
    expect(sessionHasProcessing(session)).toBe(true);
  });

  it('停住的批次不算：沒有任務看著它，等也等不到', () => {
    const [session] = buildTaskSessions(
      [batch({ session_id: 'session-1', status: 'POLLING', is_alive: false })],
      [single({ session_id: 'session-1', status: 'COMPLETED' })],
    );
    expect(sessionHasProcessing(session)).toBe(false);
  });

  it('有單檔任務還在處理', () => {
    const [session] = buildTaskSessions(
      [batch({ session_id: 'session-1', status: 'COMPLETED' })],
      [single({ session_id: 'session-1', status: 'PROCESSING' })],
    );
    expect(sessionHasProcessing(session)).toBe(true);
  });

  it('全部結束時沒有', () => {
    const [session] = buildTaskSessions(
      [batch({ session_id: 'session-1', status: 'RETRIEVED' })],
      [single({ session_id: 'session-1', status: 'FAILED' })],
    );
    expect(sessionHasProcessing(session)).toBe(false);
  });

  it('一組裡沒有任務時沒有', () => {
    expect(sessionHasProcessing({ items: [] })).toBe(false);
  });
});
