CREATE TABLE IF NOT EXISTS external_repository_snapshot (
 repo VARCHAR(191) NOT NULL,
 commit_sha CHAR(40) NOT NULL,
 archive_sha256 CHAR(64) NOT NULL,
 manifest_json JSON NOT NULL,
 PRIMARY KEY(repo,commit_sha),
 FOREIGN KEY(archive_sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS external_candidate (
 candidate_id CHAR(64) PRIMARY KEY,
 repo VARCHAR(191) NOT NULL,
 commit_sha CHAR(40) NOT NULL,
 kind VARCHAR(48) NOT NULL,
 unit_name VARCHAR(160) NULL,
 cohort SMALLINT NULL,
 department TEXT NULL,
 artifact_sha256 CHAR(64) NOT NULL,
 payload_json JSON NOT NULL,
 FOREIGN KEY(repo,commit_sha) REFERENCES external_repository_snapshot(repo,commit_sha),
 FOREIGN KEY(artifact_sha256) REFERENCES material_blob(sha256)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS external_comparison (
 comparison_id CHAR(64) PRIMARY KEY,
 payload_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
