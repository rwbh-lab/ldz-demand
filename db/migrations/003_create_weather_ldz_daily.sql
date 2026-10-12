-- 003_create_weather_ldz_daily.sql
-- ERA5 gas-day weather per LDZ, one row per gas day x LDZ x membership x weighting x variable.

CREATE TABLE IF NOT EXISTS `weather_ldz_daily` (
  `gas_day` DATE NOT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `membership` VARCHAR(64) NOT NULL,
  `weighting` VARCHAR(64) NOT NULL,
  `variable` VARCHAR(64) NOT NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `source` VARCHAR(64) NULL,
  PRIMARY KEY (`gas_day`, `ldz`, `membership`, `weighting`, `variable`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
