"""
Calendar effects on LDZ demand: day of week, bank holidays, and the Christmas period.

Bank holidays follow England & Wales, except Scotland (SC) which follows Scotland's own list (from the
`holidays` package, which tracks gov.uk). The Christmas period (24 December - 1 January) gets its own
term: offices and much industry close for the week, beyond the bank holidays themselves.
"""

from functools import lru_cache

import pandas as pd

DAYS = ("tue", "wed", "thu", "fri", "sat", "sun")  # Monday is the baseline


@lru_cache(maxsize=4)
def _bank_holidays(subdivision: str, first: int, last: int) -> frozenset:
    import holidays

    return frozenset(holidays.country_holidays("GB", subdiv=subdivision, years=range(first, last + 1)))


def features(gas_days, ldz: str) -> pd.DataFrame:
    """0/1 columns per gas day: tue..sun, bank_holiday, christmas."""
    days = pd.DatetimeIndex(gas_days)
    out = pd.DataFrame(index=days)
    weekday = days.day_of_week
    for i, name in enumerate(DAYS, start=1):
        out[name] = (weekday == i).astype(float)
    bank = _bank_holidays("SCT" if ldz == "SC" else "ENG", int(days.year.min()), int(days.year.max()))
    out["bank_holiday"] = [float(d.date() in bank) for d in days]
    out["christmas"] = (((days.month == 12) & (days.day >= 24)) | ((days.month == 1) & (days.day == 1))).astype(float)
    return out
