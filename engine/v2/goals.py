"""
engine/v2/goals.py

The match model.

  expected goals = blend(goals form, xG form)
  total          = shrunk 40% toward the league average (fitted walk-forward)
  supremacy      = blend(team-strength supremacy, Elo supremacy)
  score grid     = bivariate Poisson with a Dixon-Coles low-score correction

The output is a full score-probability grid, so every market (1X2, double
chance, totals, team totals, BTTS, handicaps) comes from one coherent object.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

import numpy as np

from engine.v2.features import TeamBook
from engine.v2.injuries import InjuryBook
from engine.v2.power import Power

MAX_GOALS = 10
RHO = -0.05
# Fitted on the 2025-27 walk-forward: shrinking the team total toward the league
# average improves both 1X2 and O/U log loss. It does NOT shrink supremacy, so
# the match balance keeps its team-specific signal.
TOTAL_SHRINK = 0.60


def poisson_pmf(mu: float, upto: int = MAX_GOALS) -> List[float]:
    mu = max(mu, 1e-9)
    out = []
    p = np.exp(-mu)
    for k in range(upto + 1):
        out.append(float(p))
        p *= mu / (k + 1)
    return out


def dc_grid(lam_h: float, lam_a: float, rho: float = RHO, max_goals: int = MAX_GOALS):
    ph = np.asarray(poisson_pmf(lam_h, max_goals))
    pa = np.asarray(poisson_pmf(lam_a, max_goals))
    grid = np.outer(ph, pa)
    # Dixon-Coles tau, only for the four low scores
    grid[0, 0] *= 1.0 - lam_h * lam_a * rho
    grid[0, 1] *= 1.0 + lam_h * rho
    grid[1, 0] *= 1.0 + lam_a * rho
    grid[1, 1] *= 1.0 - rho
    grid = np.clip(grid, 0.0, None)
    return grid / grid.sum()


@dataclass
class GoalPrediction:
    league: str
    home: str
    away: str
    lam_h: float
    lam_a: float
    grid: np.ndarray
    total: float
    supremacy: float
    sup_model: float
    sup_elo: Optional[float]
    xg_used: bool
    elo_source: str

    @property
    def expected_goals(self):
        return self.lam_h, self.lam_a

    def result(self) -> Dict[str, float]:
        g = self.grid
        h = float(np.tril(g, -1).sum())
        d = float(np.trace(g))
        a = float(np.triu(g, 1).sum())
        return {"H": h, "D": d, "A": a}

    def double_chance(self) -> Dict[str, float]:
        r = self.result()
        return {"1X": r["H"] + r["D"], "X2": r["A"] + r["D"], "12": r["H"] + r["A"]}

    def btts(self) -> Dict[str, float]:
        p_yes = float(1.0 - self.grid[0, :].sum() - self.grid[:, 0].sum() + self.grid[0, 0])
        return {"Y": max(0.0, min(1.0, p_yes)), "N": max(0.0, min(1.0, 1.0 - p_yes))}

    def total_over(self, line: float) -> float:
        n = self.grid.shape[0]
        return float(sum(self.grid[i, j] for i in range(n) for j in range(n) if i + j > line))

    def team_over(self, side: str, line: float) -> float:
        n = self.grid.shape[0]
        if side == "home":
            return float(sum(self.grid[i, j] for i in range(n) for j in range(n) if i > line))
        return float(sum(self.grid[i, j] for i in range(n) for j in range(n) if j > line))

    def handicap(self, side: str, line: float) -> float:
        """Asian handicap: stake returned on a push (integer line)."""
        n = self.grid.shape[0]
        win = push = 0.0
        for i in range(n):
            for j in range(n):
                margin = (i - j) if side == "home" else (j - i)
                if margin + line > 0:
                    win += self.grid[i, j]
                elif margin + line == 0:
                    push += self.grid[i, j]
        return float(win + 0.5 * push)


class GoalModel:
    def __init__(self, book: TeamBook, power: Power, as_of: date,
                 xg_weight: float = 0.60, elo_weight: float = 0.35,
                 injuries: Optional[InjuryBook] = None,
                 total_shrink: float = TOTAL_SHRINK):
        self.book, self.power, self.as_of = book, power, as_of
        self.xg_weight = xg_weight
        self.elo_weight = elo_weight
        self.injuries = injuries
        self.total_shrink = total_shrink
        self._cache: Dict[tuple, GoalPrediction] = {}

    def predict(self, league: str, home: str, away: str) -> GoalPrediction:
        key = (league, home, away)
        if key in self._cache:
            return self._cache[key]
        stats = self.book.expected(league, home, away, self.as_of)
        lg = self.book.league_means(league, self.as_of)

        goals = stats.get("goals")
        if goals:
            lh, la = goals.home, goals.away
        else:
            lh, la = lg["goals"].home, lg["goals"].away

        xg = stats.get("xg")
        xg_used = xg is not None
        if xg:
            lh = self.xg_weight * xg.home + (1 - self.xg_weight) * lh
            la = self.xg_weight * xg.away + (1 - self.xg_weight) * la

        total_model = lh + la
        base_total = lg["goals"].home + lg["goals"].away
        total_model = base_total + self.total_shrink * (total_model - base_total)
        sup_model = lh - la
        sup_elo = self.power.expected_supremacy(home, away, league)
        if sup_elo is None:
            sup = sup_model
        else:
            sup = self.elo_weight * sup_elo + (1 - self.elo_weight) * sup_model

        # keep the total intact; Elo only moves the balance
        lh = max(0.15, (total_model + sup) / 2.0)
        la = max(0.15, (total_model - sup) / 2.0)
        if self.injuries is not None:
            lh *= self.injuries.factor(league, home, self.as_of)
            la *= self.injuries.factor(league, away, self.as_of)
        grid = dc_grid(lh, la)
        pred = GoalPrediction(
            league=league, home=home, away=away, lam_h=lh, lam_a=la, grid=grid,
            total=total_model, supremacy=sup, sup_model=sup_model,
            sup_elo=sup_elo, xg_used=xg_used, elo_source=self.power.source,
        )
        self._cache[key] = pred
        return pred
