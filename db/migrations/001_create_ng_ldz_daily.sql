-- 001_create_ng_ldz_daily.sql
-- National Gas per-LDZ daily series (demand, CV, CWV). Long format: one row per gas day x LDZ x item.
-- Units differ by item (see the unit column): total demand is mcm, DM/NDM/UIG are kWh.

CREATE TABLE IF NOT EXISTS `ng_ldz_daily` (
  `gas_day` DATE NOT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `item` VARCHAR(64) NOT NULL,
  `data_item_id` VARCHAR(64) NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `quality` VARCHAR(64) NULL,
  `applicable_at` DATETIME NULL,
  `generated_time` DATETIME NULL,
  PRIMARY KEY (`gas_day`, `ldz`, `item`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
