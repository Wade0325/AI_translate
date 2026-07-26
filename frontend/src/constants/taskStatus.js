/** TranscriptionLog 狀態 → antd Tag 顏色與顯示文字（History、Dashboard 共用）。 */
export const STATUS_META = {
  COMPLETED: { color: 'green', label: '完成' },
  FAILED: { color: 'red', label: '失敗' },
  PROCESSING: { color: 'blue', label: '處理中' },
  PENDING: { color: 'default', label: '等待中' },
  CANCELLED: { color: 'default', label: '已取消' },
};
