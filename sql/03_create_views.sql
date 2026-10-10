USE nyc311_analytics;
CREATE OR REPLACE VIEW vw_monthly_overview AS
SELECT DATE_FORMAT(created_date, '%Y-%m-01') AS month_start,
       COUNT(*) AS request_count, SUM(is_open) AS open_count,
       ROUND(100 * SUM(is_open) / NULLIF(COUNT(*),0), 2) AS open_share_pct,
       ROUND(AVG(CASE WHEN NOT is_open THEN resolution_hours END), 2) AS mean_resolution_hours
FROM fact_service_request GROUP BY DATE_FORMAT(created_date, '%Y-%m-01');

-- MySQL 8 window functions: midpoint median and nearest-rank p90.
-- Percentiles include valid closed requests only.
CREATE OR REPLACE VIEW vw_closure_by_type AS
WITH ranked AS (
  SELECT complaint_type, agency, borough, community_board, resolution_hours,
         ROW_NUMBER() OVER (PARTITION BY complaint_type, agency, borough, community_board ORDER BY resolution_hours) AS rn,
         COUNT(*) OVER (PARTITION BY complaint_type, agency, borough, community_board) AS n
  FROM fact_service_request WHERE closed_date IS NOT NULL AND resolution_hours >= 0
), summary AS (
  SELECT complaint_type, agency, borough, community_board, MAX(n) AS closed_request_count,
         AVG(CASE WHEN rn IN (FLOOR((n + 1) / 2), FLOOR((n + 2) / 2)) THEN resolution_hours END) AS median_resolution_hours,
         MAX(CASE WHEN rn = CEIL(0.9 * n) THEN resolution_hours END) AS p90_resolution_hours
  FROM ranked GROUP BY complaint_type, agency, borough, community_board
)
SELECT complaint_type, agency, borough, community_board, closed_request_count,
       ROUND(median_resolution_hours, 2) AS median_resolution_hours,
       ROUND(p90_resolution_hours, 2) AS p90_resolution_hours
FROM summary;

CREATE OR REPLACE VIEW vw_open_backlog_age AS
SELECT unique_key, created_date, agency, agency_name, complaint_type, borough, community_board,
       TIMESTAMPDIFF(DAY, created_date, UTC_TIMESTAMP()) AS age_days,
       CASE WHEN TIMESTAMPDIFF(DAY, created_date, UTC_TIMESTAMP()) < 7 THEN '0-6 days'
            WHEN TIMESTAMPDIFF(DAY, created_date, UTC_TIMESTAMP()) < 30 THEN '7-29 days'
            WHEN TIMESTAMPDIFF(DAY, created_date, UTC_TIMESTAMP()) < 90 THEN '30-89 days'
            ELSE '90+ days' END AS age_band
FROM fact_service_request WHERE is_open = TRUE;

CREATE OR REPLACE VIEW vw_backlog_by_month AS
SELECT DATE_FORMAT(created_date, '%Y-%m-01') AS month_start, complaint_type, agency, borough, community_board,
       COUNT(*) AS open_count,
       SUM(CASE WHEN TIMESTAMPDIFF(DAY, created_date, UTC_TIMESTAMP()) >= 90 THEN 1 ELSE 0 END) AS open_90_plus
FROM fact_service_request WHERE is_open = TRUE
GROUP BY DATE_FORMAT(created_date, '%Y-%m-01'), complaint_type, agency, borough, community_board;
