CREATE TABLE IF NOT EXISTS school_web_source (
  snapshot_sha CHAR(64) PRIMARY KEY,
  unit VARCHAR(160) NOT NULL,
  observed_at VARCHAR(40) NOT NULL,
  payload_json JSON NOT NULL,
  canonical_bytes LONGBLOB NOT NULL,
  INDEX idx_web_unit_time (unit, observed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
