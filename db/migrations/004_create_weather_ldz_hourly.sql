-- 004_create_weather_ldz_hourly.sql
-- ERA5 hourly weather per LDZ (detail variants), one row per hour x LDZ x variant x variable.

CREATE TABLE IF NOT EXISTS `weather_ldz_hourly` (
  `time` DATETIME NOT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `membership` VARCHAR(64) NOT NULL,
  `weighting` VARCHAR(64) NOT NULL,
  `variable` VARCHAR(64) NOT NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `source` VARCHAR(64) NULL,
  PRIMARY KEY (`time`, `ldz`, `membership`, `weighting`, `variable`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
