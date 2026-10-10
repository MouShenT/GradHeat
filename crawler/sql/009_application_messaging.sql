CREATE TABLE IF NOT EXISTS admissions_publication_bytes (
 version_id CHAR(64) PRIMARY KEY,
 content LONGBLOB NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY(version_id) REFERENCES admissions_publication(version_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS app_task (
 task_id CHAR(36) PRIMARY KEY,
 task_type VARCHAR(80) NOT NULL,
 input_version CHAR(64) NOT NULL,
 processor_version VARCHAR(80) NOT NULL,
 scope_json JSON NOT NULL,
 status VARCHAR(32) NOT NULL,
 attempt INT UNSIGNED NOT NULL DEFAULT 1,
 last_event_sequence INT UNSIGNED NOT NULL DEFAULT 0,
 cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
 result_id CHAR(36) NULL,
 result_sha CHAR(64) NULL,
 error_code VARCHAR(80) NULL,
 created_at DATETIME(6) NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 deadline_at DATETIME(6) NOT NULL,
 INDEX idx_app_task_updated(updated_at),
 FOREIGN KEY(input_version) REFERENCES admissions_publication(version_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS app_outbox (
 message_id CHAR(36) PRIMARY KEY,
 task_id CHAR(36) NOT NULL,
 routing_key VARCHAR(80) NOT NULL,
 payload_json JSON NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'pending',
 attempts INT UNSIGNED NOT NULL DEFAULT 0,
 next_attempt_at DATETIME(6) NOT NULL,
 lease_token CHAR(36) NULL,
 lease_until DATETIME(6) NULL,
 last_error VARCHAR(80) NULL,
 created_at DATETIME(6) NOT NULL,
 sent_at DATETIME(6) NULL,
 INDEX idx_app_outbox_pending(status,next_attempt_at),
 FOREIGN KEY(task_id) REFERENCES app_task(task_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS app_inbox (
 message_id CHAR(36) PRIMARY KEY,
 task_id CHAR(36) NOT NULL,
 payload_sha CHAR(64) NOT NULL,
 payload_json JSON NOT NULL,
 received_at DATETIME(6) NOT NULL,
 disposition VARCHAR(32) NOT NULL,
 FOREIGN KEY(task_id) REFERENCES app_task(task_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS python_worker_execution (
 execution_key CHAR(64) PRIMARY KEY,
 task_id CHAR(36) NOT NULL,
 input_version CHAR(64) NOT NULL,
 input_sha CHAR(64) NOT NULL,
 processor_version VARCHAR(80) NOT NULL,
 attempt INT UNSIGNED NOT NULL,
 status VARCHAR(32) NOT NULL,
 lease_owner VARCHAR(100) NOT NULL,
 lease_until DATETIME(6) NOT NULL,
 updated_at DATETIME(6) NOT NULL,
 result_id CHAR(36) NULL,
 result_sha CHAR(64) NULL,
 error_code VARCHAR(80) NULL,
 INDEX idx_python_worker_lease(status,lease_until)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS python_worker_result (
 result_id CHAR(36) PRIMARY KEY,
 execution_key CHAR(64) NOT NULL UNIQUE,
 payload_json JSON NOT NULL,
 result_bytes LONGBLOB NOT NULL,
 result_sha CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 FOREIGN KEY(execution_key) REFERENCES python_worker_execution(execution_key)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS python_event_outbox (
 message_id CHAR(36) PRIMARY KEY,
 task_id CHAR(36) NOT NULL,
 routing_key VARCHAR(80) NOT NULL,
 payload_json JSON NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'pending',
 attempts INT UNSIGNED NOT NULL DEFAULT 0,
 next_attempt_at DATETIME(6) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 sent_at DATETIME(6) NULL,
 INDEX idx_python_event_pending(status,next_attempt_at)
) ENGINE=InnoDB;
