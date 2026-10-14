-- 007_create_demand_forecast_daily.sql
-- Demand forecasts from the ensemble, one row per run x gas day x LDZ (or GB) x statistic.

CREATE TABLE IF NOT EXISTS `demand_forecast_daily` (
  `run_date` DATE NOT NULL,
  `run_hour` BIGINT NOT NULL,
  `gas_day` DATE NOT NULL,
  `lead_days` BIGINT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `statistic` VARCHAR(64) NOT NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `model` VARCHAR(64) NULL,
  PRIMARY KEY (`run_date`, `run_hour`, `gas_day`, `ldz`, `statistic`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
