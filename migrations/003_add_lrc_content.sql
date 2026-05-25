-- Migration: transcription_logs 新增 lrc_content 欄位
-- Date: 2026-05-25
-- 新建環境會由 session.py:_migrate_add_missing_columns() 自動補齊

ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS lrc_content TEXT;
