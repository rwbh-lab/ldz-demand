-- 002_create_ng_offtake_daily.sql
-- Energy offtaken from the NTS at each LDZ offtake point (kWh/day): one row per gas day x LDZ x site.

CREATE TABLE IF NOT EXISTS `ng_offtake_daily` (
  `gas_day` DATE NOT NULL,
  `ldz` VARCHAR(64) NOT NULL,
  `site` VARCHAR(64) NOT NULL,
  `data_item_id` VARCHAR(64) NULL,
  `value` DOUBLE NULL,
  `unit` VARCHAR(64) NULL,
  `quality` VARCHAR(64) NULL,
  `applicable_at` DATETIME NULL,
  `generated_time` DATETIME NULL,
  PRIMARY KEY (`gas_day`, `ldz`, `site`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
