-- =============================================
-- Migration: 新增歷史紀錄頁面所需欄位
-- Date: 2026-02-21
-- =============================================

-- TranscriptionLog 新增欄位
ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS is_batch BOOLEAN DEFAULT FALSE;
ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS batch_id VARCHAR;
ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS provider VARCHAR;
ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS target_language VARCHAR;
ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;

-- BatchJob 新增欄位
ALTER TABLE batch_jobs ADD COLUMN IF NOT EXISTS file_count INTEGER;
ALTER TABLE batch_jobs ADD COLUMN IF NOT EXISTS completed_file_count INTEGER DEFAULT 0;
