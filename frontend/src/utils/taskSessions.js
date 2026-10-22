/**
 * 將 Task 頁的批次與單檔任務依 session_id 分組（同一次 Start = 同一組）。
 */

import { resolveSessionIdFromStorage } from './transcribeSessions'
import { TASK_STATUS } from '../constants/taskStatus'

function parseTime(value) {
  if (!value) return 0
  const t = new Date(value).getTime()
  return Number.isNaN(t) ? 0 : t
}

function countSessionFiles(items) {
  return items.reduce((sum, item) => {
    if (item.kind === "batch") {
      return sum + (item.task.file_count || item.task.files?.length || 0)
    }
    return sum + 1
  }, 0)
}

const CLUSTER_WINDOW_MS = 10 * 60 * 1000 // 同一次 Start 的檔案通常在 10 分鐘內建立

function resolveSingleSessionId(task) {
  if (task.session_id) return task.session_id
  const fromStorage = resolveSessionIdFromStorage(task.file_uid)
  if (fromStorage) return fromStorage
  return null
}

/** 無 session_id 的單檔任務：依建立時間與模型合併為同一組 */
function clusterSinglesWithoutSession(tasks) {
  const orphans = tasks.filter((t) => !resolveSingleSessionId(t))
  const withSession = tasks.filter((t) => resolveSingleSessionId(t))

  const sorted = [...orphans].sort(
    (a, b) => parseTime(a.request_timestamp) - parseTime(b.request_timestamp)
  )
  const clusters = []

  for (const task of sorted) {
    const t = parseTime(task.request_timestamp || task.completed_at)
    const last = clusters[clusters.length - 1]
    const canMerge =
      last
      && t > 0
      && t - last.endMs <= CLUSTER_WINDOW_MS
      && (task.model_used || "") === (last.model || "")

    if (canMerge) {
      last.tasks.push(task)
      last.endMs = Math.max(last.endMs, t)
    } else {
      clusters.push({
        sessionId: `cluster-${task.task_uuid}`,
        startMs: t,
        endMs: t,
        model: task.model_used || "",
        tasks: [task],
      })
    }
  }

  return { withSession, clusters }
}

/**
 * @param {Array} batchTasks  GET /batch/tasks
 * @param {Array} singleTasks GET /history/active
 * @returns {Array<{ sessionId: string, startedAt: string|null, items: Array }>}
 */
export function buildTaskSessions(batchTasks = [], singleTasks = []) {
  const sessions = new Map()

  const touch = (sessionId, startedAt) => {
    if (!sessions.has(sessionId)) {
      sessions.set(sessionId, { sessionId, startedAt: startedAt || null, items: [] })
    }
    const session = sessions.get(sessionId)
    if (startedAt) {
      const t = parseTime(startedAt)
      const cur = parseTime(session.startedAt)
      if (!session.startedAt || (t && t < cur)) {
        session.startedAt = startedAt
      }
    }
    return session
  }

  for (const task of batchTasks) {
    const sid = task.session_id || task.batch_id
    const session = touch(sid, task.created_at)
    session.items.push({ kind: "batch", task })
  }

  const { withSession, clusters } = clusterSinglesWithoutSession(singleTasks)

  for (const task of withSession) {
    const sid = resolveSingleSessionId(task)
    const startedAt = task.request_timestamp || task.completed_at
    const session = touch(sid, startedAt)
    session.items.push({ kind: "single", task })
  }

  for (const cluster of clusters) {
    const startedAt = cluster.tasks[0]?.request_timestamp || cluster.tasks[0]?.completed_at
    const session = touch(cluster.sessionId, startedAt)
    for (const task of cluster.tasks) {
      session.items.push({ kind: "single", task })
    }
  }

  return Array.from(sessions.values())
    .map((session) => ({
      ...session,
      fileCount: countSessionFiles(session.items),
    }))
    .sort((a, b) => parseTime(b.startedAt) - parseTime(a.startedAt))
}

// 批次還在進行的狀態（backend/app/core/batch_state.py 的 IN_PROGRESS）：應該有任務看著它
const BATCH_IN_PROGRESS = ["POLLING", "UPLOADING", "RECOVERING"]

/** 批次還在處理：在進行中的狀態，而且沒有查到看著它的任務已經不在。 */
export function isBatchProcessing(task) {
  return BATCH_IN_PROGRESS.includes(task.status) && task.is_alive !== false
}

/** 批次停住了：在進行中的狀態，看著它的任務卻已經不在（例如應用程式重啟了）。 */
export function isBatchInterrupted(task) {
  return BATCH_IN_PROGRESS.includes(task.status) && task.is_alive === false
}

export function isBatchCompleted(task) {
  return ["COMPLETED", "RETRIEVED"].includes(task.status)
}

export function isBatchFailed(task) {
  return task.status === "FAILED"
}

export function isSingleProcessing(task) {
  return task.status === TASK_STATUS.PROCESSING
}

export function isSingleCompleted(task) {
  return [TASK_STATUS.COMPLETED, TASK_STATUS.FAILED].includes(task.status)
}

export function sessionHasProcessing(session) {
  return session.items.some((item) =>
    item.kind === "batch"
      ? isBatchProcessing(item.task)
      : isSingleProcessing(item.task)
  )
}
