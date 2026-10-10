CREATE TABLE IF NOT EXISTS school_dossier_version (
 unit VARCHAR(160) NOT NULL,
 version_sha CHAR(64) NOT NULL,
 admissions_version CHAR(64) NOT NULL,
 observed_at VARCHAR(40) NOT NULL,
 payload_json JSON NOT NULL,
 canonical_bytes LONGBLOB NOT NULL,
 PRIMARY KEY(unit,version_sha),
 INDEX idx_dossier_admissions(admissions_version,unit)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS school_dossier_head (
 unit VARCHAR(160) PRIMARY KEY,
 version_sha CHAR(64) NOT NULL,
 FOREIGN KEY(unit,version_sha) REFERENCES school_dossier_version(unit,version_sha)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS school_content_link (
 unit VARCHAR(160) NOT NULL,
 snapshot_id CHAR(64) NOT NULL,
 attribution_weight DOUBLE NOT NULL,
 basis VARCHAR(40) NOT NULL,
 PRIMARY KEY(unit,snapshot_id),
 FOREIGN KEY(snapshot_id) REFERENCES social_content_snapshot(snapshot_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS school_search_signal (
 signal_id CHAR(64) PRIMARY KEY,
 unit VARCHAR(160) NOT NULL,
 observed_at VARCHAR(40) NOT NULL,
 payload_json JSON NOT NULL,
 INDEX idx_search_school(unit,observed_at)
) ENGINE=InnoDB;
