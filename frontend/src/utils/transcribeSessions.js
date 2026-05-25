/**
 * 瀏覽器端記錄「每次 Start」的 session，供 Task 頁在 DB 尚未寫入 session_id 時仍能分組。
 */

const STORAGE_KEY = 'ai_translate_transcribe_sessions';
const MAX_SESSIONS = 80;

export function registerTranscribeSession({ sessionId, fileUids, startedAt }) {
  if (!sessionId || !fileUids?.length) return;

  let sessions = [];
  try {
    sessions = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    sessions = [];
  }

  sessions.unshift({
    sessionId,
    fileUids: [...fileUids],
    startedAt: startedAt || new Date().toISOString(),
  });

  sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(sessions.slice(0, MAX_SESSIONS))
  );
}

export function resolveSessionIdFromStorage(fileUid) {
  if (!fileUid) return null;
  try {
    const sessions = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
    for (const session of sessions) {
      if (session.fileUids?.includes(fileUid)) {
        return session.sessionId;
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}
