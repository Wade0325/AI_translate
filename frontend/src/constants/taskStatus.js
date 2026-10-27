/**
 * 任務狀態清單：任務紀錄的 status 與 WS 狀態廣播的 status_code。
 * 和後端 backend/app/core/task_status.py 的 TaskStatus 一致，由 tests/unit/test_task_status.py 檢查。
 */
export const TASK_STATUS = Object.freeze({
  PROCESSING: 'PROCESSING',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
  BATCH_SUBMITTED: 'BATCH_SUBMITTED',
  BATCH_COMPLETED: 'BATCH_COMPLETED',
});

/** TranscriptionLog 狀態 → antd Tag 顏色與顯示文字（History 用）。 */
export const STATUS_META = {
  [TASK_STATUS.COMPLETED]: { color: 'green', label: '完成' },
  [TASK_STATUS.FAILED]: { color: 'red', label: '失敗' },
  [TASK_STATUS.PROCESSING]: { color: 'blue', label: '處理中' },
  [TASK_STATUS.CANCELLED]: { color: 'default', label: '已取消' },
};
