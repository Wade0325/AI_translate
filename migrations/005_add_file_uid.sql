-- Migration: transcription_logs 新增 file_uid
-- Date: 2026-05-25

ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS file_uid VARCHAR;

CREATE INDEX IF NOT EXISTS ix_transcription_logs_file_uid
    ON transcription_logs (file_uid);
