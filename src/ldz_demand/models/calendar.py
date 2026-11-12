"""
Calendar effects on LDZ demand: day of week, bank holidays, and the Christmas period.

Bank holidays follow England & Wales, except Scotland (SC) which follows Scotland's own list (from the
`holidays` package, which tracks gov.uk). The Christmas period (24 December - 1 January) gets its own
term: offices and much industry close for the week, beyond the bank holidays themselves.

Optional (extras=("bridge",), the challenger feature grid): bridge days, working days next to a bank
holiday or between two days off, when many take leave. The CWV model's held-out errors were 2-3 % of
mean demand too high on them in each of 2023/24-2025/26 (models.diagnostics).
"""

from functools import lru_cache

import numpy as np
import pandas as pd

DAYS = ("tue", "wed", "thu", "fri", "sat", "sun")  # Monday is the baseline
EXTRAS = ("bridge",)


@lru_cache(maxsize=4)
def _bank_holidays(subdivision: str, first: int, last: int) -> frozenset:
    import holidays

    return frozenset(holidays.country_holidays("GB", subdiv=subdivision, years=range(first, last + 1)))


def bridge(gas_days, ldz: str) -> np.ndarray:
    """True on working days next to a bank holiday, or with a day off on both sides."""
    days = pd.DatetimeIndex(gas_days)
    around = pd.date_range(days.min() - pd.Timedelta(days=1), days.max() + pd.Timedelta(days=1))
    bank = _bank_holidays("SCT" if ldz == "SC" else "ENG", int(around.year.min()), int(around.year.max()))
    hol = pd.Series([d.date() in bank for d in around], index=around)
    off = hol | (around.day_of_week >= 5)
    before, after = off.shift(1, fill_value=False), off.shift(-1, fill_value=False)
    next_to_holiday = hol.shift(1, fill_value=False) | hol.shift(-1, fill_value=False)
    out = ~off & ((before & after) | next_to_holiday)
    return out.reindex(days).to_numpy(dtype=bool)


def features(gas_days, ldz: str, extras=()) -> pd.DataFrame:
    """0/1 columns per gas day: tue..sun, bank_holiday, christmas, and any of EXTRAS asked for."""
    days = pd.DatetimeIndex(gas_days)
    out = pd.DataFrame(index=days)
    weekday = days.day_of_week
    for i, name in enumerate(DAYS, start=1):
        out[name] = (weekday == i).astype(float)
    bank = _bank_holidays("SCT" if ldz == "SC" else "ENG", int(days.year.min()), int(days.year.max()))
    out["bank_holiday"] = [float(d.date() in bank) for d in days]
    out["christmas"] = (((days.month == 12) & (days.day >= 24)) | ((days.month == 1) & (days.day == 1))).astype(float)
    if "bridge" in extras:
        out["bridge"] = bridge(days, ldz).astype(float)
    return out
