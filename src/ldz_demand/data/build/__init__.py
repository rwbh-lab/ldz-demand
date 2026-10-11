"""
Builders: raw archive (raw_dir) -> Store tables.

One builder per table. Builders read only the raw archive, so every table can be rebuilt from the
archived files without re-downloading — important for National Gas, whose portal drops old years.
"""
