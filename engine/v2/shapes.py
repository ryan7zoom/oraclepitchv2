"""
engine/v2/shapes.py

"Safe-style" picks: the high-hit-rate shapes the user actually bets.

  Favourite shapes   favourite double chance / win, optionally with a high
                     match-goals under, or the favourite to score.
  Underdog shapes    the underdog gets 2+ shots on target, 7+ / 8+ shots,
                     or 2+ corners.

Every shape is measured on the correlated match simulation (never a product
of legs) and shown with its model probability and fair price. Nothing is
filtered or adjusted by odds: the user compares the fair price with the
bookmaker's price by hand.

Favourite and underdog are decided by the model's win probabilities. Goals,
results and double chance come from the goals model; shots and corners come
from team rates (form), so those legs carry more uncertainty and are marked.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from engine.v2.goals import GoalPrediction
from engine.v2.sim import Sim


@dataclass
class Shape:
    label: str
    prob: float
    group: str          # "favourite" | "underdog"
    source: str         # "model" | "form"

    @property
    def fair(self) -> float:
        return 1.0 / self.prob if self.prob > 0 else 999.0

    def to_dict(self) -> dict:
        return {"label": self.label, "prob": round(self.prob, 4),
                "fair": round(self.fair, 2), "group": self.group, "source": self.source}


UNDER_LINES_DC = (4.5, 5.5, 6.5)
UNDER_LINES_WIN = (5.5, 6.5)


def build(pred: GoalPrediction, sim: Sim, home_name: str = "", away_name: str = "",
          include_underdog: bool = True) -> Dict[str, object]:
    home_name = home_name or pred.home
    away_name = away_name or pred.away
    r = pred.result()
    fav_home = r["H"] >= r["A"]
    fav = home_name if fav_home else away_name
    dog = away_name if fav_home else home_name

    gh, ga = sim.column("g_h"), sim.column("g_a")
    fg, dg = (gh, ga) if fav_home else (ga, gh)
    total = gh + ga
    dog_t = sim.column("t_a" if fav_home else "t_h")
    dog_s = sim.column("s_a" if fav_home else "s_h")
    dog_c = sim.column("c_a" if fav_home else "c_h")

    not_lose = fg >= dg
    win = fg > dg

    def p(*masks) -> float:
        return sim.joint(list(masks))

    out: List[Shape] = []
    for line in UNDER_LINES_DC:
        out.append(Shape(f"{fav} double chance + under {line:g} goals",
                         p(not_lose, total <= line), "favourite", "model"))
    for line in UNDER_LINES_WIN:
        out.append(Shape(f"{fav} to win + under {line:g} goals",
                         p(win, total <= line), "favourite", "model"))
    out.append(Shape(f"{fav} double chance", p(not_lose), "favourite", "model"))
    out.append(Shape(f"{fav} to win", p(win), "favourite", "model"))
    out.append(Shape(f"{fav} to score", p(fg >= 1), "favourite", "model"))

    if include_underdog:
        out.append(Shape(f"{dog} 2+ shots on target", p(dog_t >= 2), "underdog", "form"))
        out.append(Shape(f"{dog} 7+ shots", p(dog_s >= 7), "underdog", "form"))
        out.append(Shape(f"{dog} 8+ shots", p(dog_s >= 8), "underdog", "form"))
        out.append(Shape(f"{dog} 2+ corners", p(dog_c >= 2), "underdog", "form"))

    out.sort(key=lambda s: -s.prob)
    return {
        "favourite": fav, "underdog": dog,
        "fav_win_prob": float(r["H"] if fav_home else r["A"]),
        "underdog_shown": include_underdog,
        "shapes": out,
    }
