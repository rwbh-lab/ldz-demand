"""
Store interface.

Ingestors and loaders talk only to this interface. Implementations:
- CsvCacheStore (this package) — default, database = false.
- A database store — supplied by the caller when database = true; never imported here.
"""
