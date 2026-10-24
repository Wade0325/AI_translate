// @ts-nocheck
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { createMemoryStorage } from '../test/memoryStorage';
import { registerTranscribeSession, resolveSessionIdFromStorage } from './transcribeSessions';

// 把分頁裡存的每一筆資料都換成不是 JSON 的字串，不必知道模組用哪個 key
function corruptSessionStorage() {
  for (let i = 0; i < sessionStorage.length; i++) {
    sessionStorage.setItem(sessionStorage.key(i), '{不是 JSON');
  }
}

beforeEach(() => {
  vi.stubGlobal('sessionStorage', createMemoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('轉錄頁每按一次開始，就在這個分頁記下送出了哪些檔案', () => {
  it('記下之後，用檔案的 uid 查得到是哪一次開始', () => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a', 'file-b'] });
    expect(resolveSessionIdFromStorage('file-b')).toBe('session-1');
  });

  it('沒記過的檔案查不到', () => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a'] });
    expect(resolveSessionIdFromStorage('file-z')).toBeNull();
  });

  it('同一個檔案在兩次開始都送出時，查到最近的那次', () => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a'] });
    registerTranscribeSession({ sessionId: 'session-2', fileUids: ['file-a'] });
    expect(resolveSessionIdFromStorage('file-a')).toBe('session-2');
  });

  it('只留最近 80 次，更早的查不到', () => {
    for (let i = 1; i <= 81; i++) {
      registerTranscribeSession({ sessionId: `session-${i}`, fileUids: [`file-${i}`] });
    }
    expect(resolveSessionIdFromStorage('file-1')).toBeNull();
    expect(resolveSessionIdFromStorage('file-2')).toBe('session-2');
  });

  it.each([
    { sessionId: '', fileUids: ['file-a'] },
    { sessionId: 'session-1', fileUids: [] },
    { sessionId: 'session-1', fileUids: undefined },
  ])('沒有 session id 或沒有檔案時什麼都不記（sessionId: $sessionId，fileUids: $fileUids）', (session) => {
    registerTranscribeSession(session);
    expect(sessionStorage.length).toBe(0);
  });

  it.each(['', null, undefined])('沒有檔案 uid（%j）時查不到', (fileUid) => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a'] });
    expect(resolveSessionIdFromStorage(fileUid)).toBeNull();
  });

  it('分頁裡的紀錄壞掉時當作沒有紀錄', () => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a'] });
    corruptSessionStorage();
    expect(resolveSessionIdFromStorage('file-a')).toBeNull();
  });

  it('分頁裡的紀錄壞掉時，照樣記下新的一次', () => {
    registerTranscribeSession({ sessionId: 'session-1', fileUids: ['file-a'] });
    corruptSessionStorage();
    registerTranscribeSession({ sessionId: 'session-2', fileUids: ['file-b'] });
    expect(resolveSessionIdFromStorage('file-b')).toBe('session-2');
  });
});
