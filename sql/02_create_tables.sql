USE nyc311_analytics;
CREATE TABLE IF NOT EXISTS stg_service_request (
  unique_key VARCHAR(32) NOT NULL PRIMARY KEY,
  payload JSON NOT NULL,
  staged_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS fact_service_request (
  unique_key VARCHAR(32) NOT NULL PRIMARY KEY,
  created_date DATETIME NOT NULL,
  closed_date DATETIME NULL,
  agency VARCHAR(16) NULL,
  agency_name VARCHAR(255) NULL,
  complaint_type VARCHAR(255) NULL,
  descriptor VARCHAR(255) NULL,
  status VARCHAR(100) NULL,
  borough VARCHAR(40) NULL,
  community_board VARCHAR(40) NULL,
  resolution_hours DECIMAL(14,3) NULL,
  is_open BOOLEAN NOT NULL,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX ix_fact_created (created_date),
  INDEX ix_fact_type_created (complaint_type, created_date),
  INDEX ix_fact_agency_created (agency, created_date),
  INDEX ix_fact_geo_created (borough, community_board, created_date),
  INDEX ix_fact_open_created (is_open, created_date),
  CONSTRAINT chk_resolution_nonnegative CHECK (resolution_hours IS NULL OR resolution_hours >= 0)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS etl_run_log (
  run_id CHAR(36) NOT NULL PRIMARY KEY,
  started_at DATETIME NOT NULL,
  ended_at DATETIME NULL,
  status ENUM('running','success','failed') NOT NULL,
  source_start DATE NULL,
  source_end_exclusive DATE NULL,
  records_fetched INT NOT NULL DEFAULT 0,
  records_inserted INT NOT NULL DEFAULT 0,
  records_updated INT NOT NULL DEFAULT 0,
  records_rejected INT NOT NULL DEFAULT 0,
  error_summary VARCHAR(1000) NULL
) ENGINE=InnoDB;
