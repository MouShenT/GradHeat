CREATE TABLE IF NOT EXISTS material_blob (
 sha256 CHAR(64) PRIMARY KEY,
 byte_size BIGINT UNSIGNED NOT NULL,
 chunk_count INT UNSIGNED NOT NULL,
 media_type VARCHAR(120) NOT NULL,
 state VARCHAR(16) NOT NULL,
 verified_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS material_chunk (
 sha256 CHAR(64) NOT NULL,
 ordinal INT UNSIGNED NOT NULL,
 content MEDIUMBLOB NOT NULL,
 PRIMARY KEY (sha256,ordinal),
 FOREIGN KEY (sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS material_location (
 location_id CHAR(64) PRIMARY KEY,
 sha256 CHAR(64) NOT NULL,
 local_path TEXT NOT NULL,
 kind VARCHAR(32) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY (sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS collection_run (
 run_id VARCHAR(80) PRIMARY KEY,
 started_at VARCHAR(40) NOT NULL,
 summary_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS collection_observation (
 observation_id CHAR(64) PRIMARY KEY,
 run_id VARCHAR(80) NOT NULL,
 unit_name VARCHAR(160) NOT NULL,
 url TEXT NOT NULL,
 sha256 CHAR(64) NULL,
 state VARCHAR(48) NOT NULL,
 payload_json JSON NOT NULL,
 FOREIGN KEY (run_id) REFERENCES collection_run(run_id),
 FOREIGN KEY (sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS admissions_publication (
 version_id CHAR(64) PRIMARY KEY,
 data_as_of VARCHAR(40) NOT NULL,
 payload_json JSON NOT NULL,
 internal_manifest JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS admissions_head (
 name VARCHAR(32) PRIMARY KEY,
 version_id CHAR(64) NOT NULL,
 FOREIGN KEY (version_id) REFERENCES admissions_publication(version_id)
) ENGINE=InnoDB;
