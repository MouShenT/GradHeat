CREATE TABLE IF NOT EXISTS corroboration_observation (
 observation_id CHAR(64) PRIMARY KEY,
 scope_id CHAR(64) NOT NULL,
 field_name VARCHAR(80) NOT NULL,
 origin_id VARCHAR(191) NOT NULL,
 official TINYINT NOT NULL,
 artifact_sha256 CHAR(64) NULL,
 payload_json JSON NOT NULL,
 INDEX idx_corroboration_scope(scope_id,field_name),
 FOREIGN KEY(artifact_sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS corroboration_decision (
 decision_id CHAR(64) PRIMARY KEY,
 policy_version VARCHAR(80) NOT NULL,
 scope_id CHAR(64) NOT NULL,
 field_name VARCHAR(80) NOT NULL,
 distinct_origins INT NOT NULL,
 verification_state VARCHAR(48) NOT NULL,
 official_state VARCHAR(48) NOT NULL,
 payload_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 INDEX idx_corroboration_decision(scope_id,field_name)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS corroboration_run (
 run_id CHAR(64) PRIMARY KEY,
 payload_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
