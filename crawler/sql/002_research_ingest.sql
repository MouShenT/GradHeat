-- Additive research storage; never applies or rewrites the legacy school schema.
CREATE TABLE IF NOT EXISTS research_schema_migration (
    migration_id VARCHAR(100) PRIMARY KEY,
    checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS research_import_batch (
    batch_id CHAR(64) PRIMARY KEY,
    as_of_date DATE NOT NULL,
    target_year SMALLINT NOT NULL,
    source_snapshot VARCHAR(100) NOT NULL,
    state VARCHAR(32) NOT NULL,
    manifest_json JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS research_record (
    record_id CHAR(64) PRIMARY KEY,
    kind VARCHAR(48) NOT NULL,
    unit_name VARCHAR(160) NOT NULL,
    cohort SMALLINT NULL,
    department TEXT NULL,
    major_code VARCHAR(32) NULL,
    study_mode VARCHAR(64) NULL,
    verification_state VARCHAR(48) NOT NULL,
    eligible_11408 TINYINT NULL,
    plan_raw TEXT NULL,
    ordinary_quota INT NULL,
    payload_json JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_research_unit_year (unit_name,cohort,kind),
    INDEX idx_research_kind_state (kind,verification_state),
    CHECK (eligible_11408 IS NULL OR eligible_11408 IN (0,1)),
    CHECK (ordinary_quota IS NULL OR ordinary_quota >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS research_batch_record (
    batch_id CHAR(64) NOT NULL,
    record_id CHAR(64) NOT NULL,
    PRIMARY KEY (batch_id,record_id),
    FOREIGN KEY (batch_id) REFERENCES research_import_batch(batch_id),
    FOREIGN KEY (record_id) REFERENCES research_record(record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS research_artifact (
    sha256 CHAR(64) PRIMARY KEY,
    byte_size BIGINT NOT NULL,
    artifact_path TEXT NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS research_record_artifact (
    record_id CHAR(64) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (record_id,sha256),
    FOREIGN KEY (record_id) REFERENCES research_record(record_id),
    FOREIGN KEY (sha256) REFERENCES research_artifact(sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
