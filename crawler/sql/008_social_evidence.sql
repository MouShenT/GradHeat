CREATE TABLE IF NOT EXISTS social_collection_run (
 run_id VARCHAR(80) PRIMARY KEY,
 started_at VARCHAR(40) NOT NULL,
 state VARCHAR(40) NOT NULL,
 summary_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS social_content_snapshot (
 snapshot_id CHAR(64) PRIMARY KEY,
 run_id VARCHAR(80) NOT NULL,
 platform VARCHAR(24) NOT NULL,
 content_id VARCHAR(120) NOT NULL,
 observed_at VARCHAR(40) NOT NULL,
 published_at VARCHAR(40) NULL,
 artifact_sha256 CHAR(64) NOT NULL,
 content_sha256 CHAR(64) NOT NULL,
 content_level VARCHAR(32) NOT NULL,
 payload_json JSON NOT NULL,
 INDEX idx_social_content(platform,content_id,observed_at),
 FOREIGN KEY(run_id) REFERENCES social_collection_run(run_id),
 FOREIGN KEY(artifact_sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS social_claim (
 claim_id CHAR(64) PRIMARY KEY,
 snapshot_id CHAR(64) NOT NULL,
 review_state VARCHAR(40) NOT NULL,
 payload_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY(snapshot_id) REFERENCES social_content_snapshot(snapshot_id)
) ENGINE=InnoDB;
