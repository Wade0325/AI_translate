-- 凍結的 SQLite schema：models.py @ 42e19d1d0b4cfaf21ef6767c0dd1d0e67b8e6d64。既有的凍結檔一律不改，見 tests/unit/test_sqlite_upgrade.py。

CREATE TABLE batch_jobs (
	batch_id VARCHAR NOT NULL, 
	session_id VARCHAR, 
	gemini_job_name VARCHAR, 
	status VARCHAR, 
	task_params_json TEXT, 
	file_mapping_json TEXT, 
	file_durations_json TEXT, 
	file_log_uuids_json TEXT, 
	results_json TEXT, 
	celery_task_id VARCHAR, 
	file_count INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (batch_id)
);

CREATE TABLE model_configurations (
	provider VARCHAR NOT NULL, 
	api_keys TEXT, 
	model VARCHAR, 
	prompt TEXT, 
	last_updated DATETIME, 
	PRIMARY KEY (provider)
);

CREATE TABLE transcript_segments (
	id INTEGER NOT NULL, 
	task_uuid UUID NOT NULL, 
	seg_key VARCHAR NOT NULL, 
	seq INTEGER NOT NULL, 
	start_sec FLOAT NOT NULL, 
	end_sec FLOAT, 
	speaker VARCHAR, 
	text TEXT, 
	text_alt TEXT, 
	source VARCHAR, 
	words_json TEXT, 
	confidence FLOAT, 
	review_state VARCHAR, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_transcript_segments_key UNIQUE (task_uuid, seg_key), 
	FOREIGN KEY(task_uuid) REFERENCES transcription_logs (task_uuid) ON DELETE CASCADE
);

CREATE TABLE transcription_logs (
	task_uuid UUID NOT NULL, 
	request_timestamp DATETIME, 
	status VARCHAR, 
	original_filename VARCHAR, 
	audio_duration_seconds FLOAT, 
	processing_time_seconds FLOAT, 
	model_used VARCHAR, 
	source_language VARCHAR, 
	total_tokens INTEGER, 
	cost FLOAT, 
	error_message TEXT, 
	is_batch BOOLEAN, 
	batch_id VARCHAR, 
	provider VARCHAR, 
	target_language VARCHAR, 
	completed_at DATETIME, 
	lrc_content TEXT, 
	file_uid VARCHAR, 
	session_id VARCHAR, 
	service_tier_used VARCHAR, 
	audio_filename VARCHAR, 
	PRIMARY KEY (task_uuid), 
	FOREIGN KEY(batch_id) REFERENCES batch_jobs (batch_id) ON DELETE SET NULL
);

CREATE INDEX ix_batch_jobs_celery_task_id ON batch_jobs (celery_task_id);

CREATE INDEX ix_batch_jobs_session_id ON batch_jobs (session_id);

CREATE INDEX ix_batch_jobs_status ON batch_jobs (status);

CREATE INDEX ix_transcript_segments_task_uuid ON transcript_segments (task_uuid);

CREATE INDEX ix_transcription_logs_batch_id ON transcription_logs (batch_id);

CREATE INDEX ix_transcription_logs_file_uid ON transcription_logs (file_uid);

CREATE INDEX ix_transcription_logs_request_timestamp ON transcription_logs (request_timestamp);

CREATE INDEX ix_transcription_logs_session_id ON transcription_logs (session_id);

CREATE INDEX ix_transcription_logs_status ON transcription_logs (status);

