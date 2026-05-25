-- Migration: 新增 session_id，用於 Task 頁依「每次 Start」分組
-- Date: 2026-05-25

ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS session_id VARCHAR;
ALTER TABLE batch_jobs ADD COLUMN IF NOT EXISTS session_id VARCHAR;

CREATE INDEX IF NOT EXISTS ix_transcription_logs_session_id
    ON transcription_logs (session_id);

CREATE INDEX IF NOT EXISTS ix_batch_jobs_session_id
    ON batch_jobs (session_id);
