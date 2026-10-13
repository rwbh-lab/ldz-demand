-- 006_create_ng_forecast_daily.sql
-- National Gas forecasts per LDZ (total demand, CWV), one row per gas day x LDZ x item x issue.

CREATE TABLE IF NOT EXISTS `ng_forecast_daily` (
  `gas_day` DATE NOT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `item` VARCHAR(64) NOT NULL,
  `issued_at` DATETIME NOT NULL,
  `issue_day` BIGINT NULL,
  `data_item_id` VARCHAR(64) NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `quality` VARCHAR(64) NULL,
  `generated_time` DATETIME NULL,
  PRIMARY KEY (`gas_day`, `ldz`, `item`, `issued_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
