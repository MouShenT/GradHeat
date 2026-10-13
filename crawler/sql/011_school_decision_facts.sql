CREATE TABLE IF NOT EXISTS school_decision_fact (
 fact_sha CHAR(64) PRIMARY KEY,
 unit VARCHAR(160) NOT NULL,
 cohort INT NOT NULL,
 observed_at VARCHAR(40) NOT NULL,
 payload_json JSON NOT NULL,
 canonical_bytes LONGBLOB NOT NULL,
 INDEX idx_school_fact(unit,cohort,observed_at)
) ENGINE=InnoDB;
