"""
engine/v2/sim.py

Correlated match simulation for the same-game builder.

The goal marginals come from the Dixon-Coles model. Corners, shots, shots on
target and cards come from team rates with a negative-binomial dispersion.
A Gaussian copula links them with correlations measured from league history,
so a builder's joint probability is not the naive product of its legs.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import erf
from typing import Dict, List, Optional, Sequence

import numpy as np

from engine.v2.features import LEAGUES, TeamBook
from engine.v2.goals import GoalPrediction

VARS = ["g_h", "g_a", "c_h", "c_a", "s_h", "s_a", "t_h", "t_a", "yc_h", "yc_a"]
MAX = {"g": 10, "c": 30, "s": 45, "t": 20, "yc": 12}
DISPERSION = {"g": 0.0, "c": 0.08, "s": 0.06, "t": 0.05, "yc": 0.10}
DEFAULT_MEANS = {"c": 5.0, "s": 12.0, "t": 4.0, "yc": 2.0}


def _nb_pmf(mu: float, alpha: float, upto: int) -> np.ndarray:
    mu = max(mu, 1e-9)
    if alpha < 1e-6:
        out = np.empty(upto + 1)
        p = np.exp(-mu)
        for k in range(upto + 1):
            out[k] = p
            p *= mu / (k + 1)
        return out
    r = 1.0 / alpha
    q = r / (r + mu)
    out = np.empty(upto + 1)
    p = q ** r
    for k in range(upto + 1):
        out[k] = p
        p *= (k + r) / (k + 1) * (1 - q)
    return out


def nearest_corr(c: np.ndarray) -> np.ndarray:
    c = (c + c.T) / 2.0
    w, v = np.linalg.eigh(c)
    w = np.clip(w, 1e-4, None)
    c = (v * w) @ v.T
    d = np.sqrt(np.diag(c))
    return c / np.outer(d, d)


def estimate_corr(book: TeamBook, league: str, as_of: date) -> np.ndarray:
    floor = as_of - timedelta(days=730)
    rows = []
    for m in book.raw.get(league, []):
        if not (floor <= m.date < as_of):
            continue
        vals = [m.ft_h, m.ft_a, m.co_h, m.co_a, m.sh_h, m.sh_a,
                m.sot_h, m.sot_a, m.yc_h, m.yc_a]
        if any(v is None for v in vals):
            continue
        rows.append(vals)
    if len(rows) < 200:
        return np.eye(len(VARS))
    x = np.asarray(rows, dtype=float)
    x = (x - x.mean(axis=0)) / np.maximum(x.std(axis=0), 1e-6)
    return nearest_corr(np.corrcoef(x, rowvar=False))


@dataclass
class Sim:
    data: np.ndarray
    seed: int

    def __len__(self):
        return self.data.shape[0]

    def column(self, name: str) -> np.ndarray:
        return self.data[:, VARS.index(name)]

    def probability(self, mask: np.ndarray) -> float:
        return float(mask.mean()) if len(mask) else 0.0

    def joint(self, masks: Sequence[np.ndarray]) -> float:
        if not masks:
            return 1.0
        return float(np.logical_and.reduce(masks).mean())


def simulate(pred: GoalPrediction, stats: Dict[str, object], corr: np.ndarray,
             n: int = 20000, seed: int = 7) -> Sim:
    rng = np.random.default_rng(seed)
    means = {
        "g_h": pred.lam_h, "g_a": pred.lam_a,
    }
    for stem, key in (("c", "corners"), ("s", "shots"), ("t", "sot"), ("yc", "cards")):
        line = stats.get(key)
        mh = getattr(line, "home", None) if line is not None else None
        ma = getattr(line, "away", None) if line is not None else None
        means[f"{stem}_h"] = mh if mh is not None else DEFAULT_MEANS[stem]
        means[f"{stem}_a"] = ma if ma is not None else DEFAULT_MEANS[stem]

    # one pmf/cdf per variable
    cdfs = []
    for name in VARS:
        stem = name.split("_")[0]
        pmf = _nb_pmf(means[name], DISPERSION[stem], MAX[stem])
        cdfs.append(np.cumsum(pmf / max(pmf.sum(), 1e-12)))

    z = rng.multivariate_normal(np.zeros(len(VARS)), corr, size=n)
    u = 0.5 * (1.0 + np.vectorize(erf)(z / np.sqrt(2.0)))  # standard normal CDF
    u = np.clip(u, 0.0, 1.0 - 1e-12)
    data = np.empty((n, len(VARS)), dtype=np.uint16)
    for j in range(len(VARS)):
        data[:, j] = np.searchsorted(cdfs[j], u[:, j], side="right")
    return Sim(data, seed)
