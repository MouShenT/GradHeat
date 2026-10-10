CREATE TABLE IF NOT EXISTS personal_comparison (
 comparison_id CHAR(64) PRIMARY KEY,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 title VARCHAR(120) NOT NULL,
 data_version CHAR(64) NOT NULL,
 analysis_version VARCHAR(80) NOT NULL,
 candidate_count INT NOT NULL,
 result_json JSON NOT NULL,
 report_md MEDIUMTEXT NOT NULL,
 INDEX idx_personal_comparison_created(created_at),
 FOREIGN KEY(data_version) REFERENCES admissions_publication(version_id)
) ENGINE=InnoDB;
