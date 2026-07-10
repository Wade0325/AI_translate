-- Migration: transcription_logs 新增 service_tier_used
-- 值域：standard / flex / batch
-- Date: 2026-05-25

ALTER TABLE transcription_logs ADD COLUMN IF NOT EXISTS service_tier_used VARCHAR;
