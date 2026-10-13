-- 005_create_ens_ldz_daily.sql
-- Ensemble gas-day forecast weather per LDZ, one row per run x member x gas day x LDZ x variant x variable x method.

CREATE TABLE IF NOT EXISTS `ens_ldz_daily` (
  `run_date` DATE NOT NULL,
  `run_hour` BIGINT NOT NULL,
  `member` BIGINT NOT NULL,
  `gas_day` DATE NOT NULL,
  `lead_days` BIGINT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `membership` VARCHAR(64) NOT NULL,
  `weighting` VARCHAR(64) NOT NULL,
  `variable` VARCHAR(64) NOT NULL,
  `method` VARCHAR(64) NOT NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `coverage_h` DOUBLE NULL,
  PRIMARY KEY (`run_date`, `run_hour`, `member`, `gas_day`, `ldz`, `membership`, `weighting`, `variable`, `method`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
