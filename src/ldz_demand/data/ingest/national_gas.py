"""
National Gas Transmission data portal ingestor.

Public CSV API, no auth. Pulls per-LDZ total demand, DM demand, NDM demand and CWV.
History is a rolling ~5 years, so every raw pull is archived untouched.
"""
