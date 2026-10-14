"""
The Composite Weather Variable form, fitted to our own weather inputs.

Same structure as the official CWV (Xoserve, Composite Weather Variable, September 2026; see
docs/methodology.md §2.1), with our own seasonal term S in place of the pseudo seasonal normal
(methodology §5.3, experiment 3):

    E_t   = y · E_t−1 + (1 − y) · T_t                                   effective temperature
    CW_t  = I1 · E_t + (1 − I1) · S_t − I2 · max(0, W_t − W0) · max(0, T0 − T_t) + S0 · SR_t
    CWV_t = V1 + q · (V2 − V1)       if CW_t ≥ V2                        summer cut-off
          = V1 + q · (CW_t − V1)     if V1 < CW_t < V2                   transition
          = CW_t                     if V0 ≤ CW_t ≤ V1                   normal
          = CW_t + I3 · (CW_t − V0)  if CW_t < V0                        cold-weather upturn

T gas-day mean temperature (°C), W gas-day mean 10 m wind speed (m/s — the official form uses knots),
SR gas-day mean solar radiation (W m-2). The seasonal term S is one of (SEASONAL):
- "none":     no seasonal term (I1 = 1);
- "slow":     a slow "heating-season" temperature, S_t = ys · S_t−1 + (1 − ys) · T_t (I1, ys fitted);
- "calendar": a smooth day-of-year shape g shared by all LDZs, added as + Sc · g_t with I1 = 1 and Sc
              (°C) fitted per LDZ (the shape pooled; see ldz_demand.models.demand.fit_joint). This is
              the I1 form with S = mean temperature + shape, rewritten: with a free-sized shape the I1
              form can be rescaled without changing the fit (V0-V2, I2, S0 follow), so it has no unique
              solution; here E keeps weight 1 and CW stays in °C.
The transform itself is ldz_demand.models.demand.composite. Fitted per LDZ; start values and some
bounds come from the published 2025 parameters (converted to our units). V2 is parametrised as V1 + dV
so it stays above V1.
"""

from dataclasses import dataclass, replace

import numpy as np

KNOT = 0.514444  # m/s

# Published CWV parameters per LDZ, in force 1 Oct 2025 - 30 Sep 2030 (Xoserve, September 2026). W0 in knots.
PUBLISHED = {
    "EA": dict(y=0.442, I1=0.720, I2=0.012, I3=0.065, V0=3.774, V1=15.312, V2=18.901, q=0.391, W0=-2.296, T0=14.837, S0=0.632),
    "EM": dict(y=0.437, I1=0.683, I2=0.009, I3=0.049, V0=4.222, V1=12.832, V2=16.490, q=0.446, W0=-1.988, T0=17.872, S0=0.778),
    "NE": dict(y=0.429, I1=0.669, I2=0.009, I3=0.024, V0=3.063, V1=12.853, V2=16.624, q=0.454, W0=-2.306, T0=21.068, S0=0.759),
    "NO": dict(y=0.494, I1=0.661, I2=0.009, I3=0.130, V0=2.388, V1=12.240, V2=15.320, q=0.477, W0=-1.826, T0=16.504, S0=0.950),
    "NT": dict(y=0.496, I1=0.724, I2=0.014, I3=0.078, V0=4.995, V1=15.256, V2=19.309, q=0.439, W0=-5.875, T0=14.574, S0=0.598),
    "NW": dict(y=0.469, I1=0.634, I2=0.008, I3=0.227, V0=3.041, V1=12.513, V2=16.192, q=0.479, W0=-4.817, T0=23.705, S0=0.938),
    "SC": dict(y=0.476, I1=0.661, I2=0.010, I3=0.138, V0=1.173, V1=12.672, V2=16.119, q=0.497, W0=-5.186, T0=16.046, S0=0.629),
    "SE": dict(y=0.426, I1=0.756, I2=0.006, I3=0.141, V0=2.658, V1=14.182, V2=18.640, q=0.373, W0=-0.610, T0=21.613, S0=0.470),
    "SO": dict(y=0.434, I1=0.698, I2=0.014, I3=0.090, V0=5.000, V1=15.213, V2=18.028, q=0.427, W0=-5.758, T0=13.187, S0=0.654),
    "SW": dict(y=0.440, I1=0.626, I2=0.009, I3=0.162, V0=3.982, V1=13.511, V2=17.044, q=0.355, W0=0.511, T0=21.866, S0=0.802),
    "WM": dict(y=0.451, I1=0.688, I2=0.010, I3=0.105, V0=4.996, V1=13.173, V2=17.328, q=0.364, W0=-4.105, T0=19.128, S0=0.751),
    "WN": dict(y=0.466, I1=0.600, I2=0.011, I3=0.338, V0=3.549, V1=12.796, V2=16.520, q=0.452, W0=-2.910, T0=18.139, S0=0.861),
    "WS": dict(y=0.477, I1=0.653, I2=0.006, I3=0.114, V0=5.000, V1=13.965, V2=16.525, q=0.385, W0=-3.815, T0=19.590, S0=0.958),
}

NAMES = ("y", "I2", "W0", "T0", "S0", "V0", "I3", "V1", "dV", "q")
SEASONAL = {"none": (), "slow": ("I1", "ys"), "calendar": ("Sc",), "slow_calendar": ("I1", "ys", "Sc")}  # seasonal term -> extra parameters


COLD = {  # cold-end form -> parameters held fixed (from `fixed_values`)
    "fitted": (),                  # V0, I3 fitted, I3 <= max(0.4, 2 x published)
    "strong": (),                  # as fitted, I3 up to 1.5
    "linear": ("V0", "I3"),        # no upturn: I3 = 0
    "published": ("V0", "I3"),     # the published upturn
}


EXTREMES = ("m_min", "m_max")


def free_names(seasonal: str = "none", cold: str = "fitted", extremes: bool = False, solar: bool = True) -> tuple[str, ...]:
    """The parameters fitted for this seasonal term, cold-end form and variables (the rest are fixed)."""
    names = NAMES + SEASONAL[seasonal] + (EXTREMES if extremes else ())
    return tuple(n for n in names if n not in COLD[cold] and (solar or n != "S0"))


def fixed_values(ldz: str, cold: str = "fitted", solar: bool = True) -> "CWVParams":
    """Start values, with the parameters this form holds fixed (the cold end; S0 = 0 without solar)."""
    p = start(ldz)  # S0 starts at 0 already
    if cold == "linear":
        return replace(p, I3=0.0)
    return p  # "published": start() already holds the published V0, I3


@dataclass(frozen=True)
class CWVParams:
    y: float
    I2: float   # wind chill, per (m/s · °C)
    W0: float   # wind speed above which wind chill applies, m/s
    T0: float   # temperature below which wind chill applies, °C
    S0: float   # solar term, per W m-2
    V0: float   # cold-weather upturn below this CW
    I3: float   # cold-weather upturn strength
    V1: float   # summer transition starts at this CW
    dV: float   # V2 - V1: width of the transition
    q: float    # slope in the transition
    I1: float = 1.0   # weight on the effective temperature; 1 - I1 on the seasonal term
    ys: float = 0.95  # memory of the slow heating-season temperature ("slow" only)
    Sc: float = 0.0   # size of the calendar shape, °C ("calendar" only)
    m_min: float = 0.0  # weight on the day's minimum temperature (extremes only): T = mean + m_min·(min − mean) + …
    m_max: float = 0.0  # … + m_max·(max − mean)

    @property
    def V2(self) -> float:
        return self.V1 + self.dV

    def vector(self, names=NAMES) -> np.ndarray:
        return np.array([getattr(self, n) for n in names], dtype=float)

    @classmethod
    def from_vector(cls, v, names=NAMES, base: "CWVParams | None" = None) -> "CWVParams":
        """From values for `names`; any others from `base` (or the defaults)."""
        values = dict(zip(names, map(float, v)))
        return replace(base, **values) if base is not None else cls(**values)


def start(ldz: str) -> CWVParams:
    """Start values from the published parameters, in our units. S0 starts near zero: the official solar
    input is in different units (the fit sets the scale)."""
    p = PUBLISHED[ldz]
    return CWVParams(y=p["y"], I2=p["I2"] / KNOT, W0=p["W0"] * KNOT, T0=p["T0"], S0=0.0,
                     V0=p["V0"], I3=p["I3"], V1=p["V1"], dV=p["V2"] - p["V1"], q=p["q"], I1=p["I1"])


def bounds(ldz: str, names=NAMES, cold: str = "fitted") -> tuple[np.ndarray, np.ndarray]:
    """(lower, upper) per parameter. The cold-weather upturn strength is held near the published values,
    as five years have few cold days; the rest is free within physically sensible ranges. V0 and T0 were
    first bounded more tightly (published V0 ± 2, T0 ≤ 25) and sat on those bounds in most fits."""
    p = PUBLISHED[ldz]
    lo = dict(y=0.05, I2=0.0, W0=-10.0, T0=5.0, S0=-0.05, V0=p["V0"] - 3.0, I3=0.0, V1=8.0, dV=0.5, q=0.0,
              I1=0.2, ys=0.85, Sc=-8.0, m_min=0.0, m_max=0.0)
    hi = dict(y=0.95, I2=0.2, W0=15.0, T0=35.0, S0=0.05, V0=p["V0"] + 6.0, I3=max(0.4, 2 * p["I3"]), V1=22.0,
              dV=12.0, q=1.0, I1=1.0, ys=0.98, Sc=8.0, m_min=1.0, m_max=1.0)
    if cold == "strong":
        hi["I3"] = 1.5  # ys 0.85-0.98: a time constant of about 1 week to 2 months
    return np.array([lo[n] for n in names]), np.array([hi[n] for n in names])
