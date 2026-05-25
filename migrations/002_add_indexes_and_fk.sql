-- =============================================
-- Migration: 為查詢熱路徑補上 index，並建立 transcription_logs.batch_id 與
-- batch_jobs.batch_id 之間的外鍵
-- Date: 2026-05-24
--
-- 注意：
-- 1. 新建環境會由 backend/app/database/session.py:_migrate_add_missing_indexes()
--    自動補齊 index；本檔僅供既有 DB 一次性升級使用。
-- 2. 加入 FK 前，請先清理 batch_id 是孤兒（在 batch_jobs 中找不到）的 row：
--      UPDATE transcription_logs
--      SET batch_id = NULL
--      WHERE batch_id IS NOT NULL
--        AND batch_id NOT IN (SELECT batch_id FROM batch_jobs);
-- =============================================

-- Index for transcription_logs ---------------------------------
CREATE INDEX IF NOT EXISTS ix_transcription_logs_request_timestamp
    ON transcription_logs (request_timestamp);

CREATE INDEX IF NOT EXISTS ix_transcription_logs_status
    ON transcription_logs (status);

CREATE INDEX IF NOT EXISTS ix_transcription_logs_batch_id
    ON transcription_logs (batch_id);

-- Index for batch_jobs ------------------------------------------
CREATE INDEX IF NOT EXISTS ix_batch_jobs_status
    ON batch_jobs (status);

CREATE INDEX IF NOT EXISTS ix_batch_jobs_celery_task_id
    ON batch_jobs (celery_task_id);

-- Foreign Key ---------------------------------------------------
-- PostgreSQL 不支援 IF NOT EXISTS 於 ADD CONSTRAINT，故使用 DO 區塊
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_transcription_logs_batch_id'
          AND table_name = 'transcription_logs'
    ) THEN
        ALTER TABLE transcription_logs
            ADD CONSTRAINT fk_transcription_logs_batch_id
            FOREIGN KEY (batch_id)
            REFERENCES batch_jobs (batch_id)
            ON DELETE SET NULL;
    END IF;
END $$;
