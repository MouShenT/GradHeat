CREATE TABLE IF NOT EXISTS school_search_signal_bytes (
    signal_id CHAR(64) NOT NULL PRIMARY KEY,
    canonical_bytes LONGBLOB NOT NULL
) ENGINE=InnoDB;
