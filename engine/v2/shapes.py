"""
engine/v2/shapes.py

Safe-style builder: ONE same-game bet builder per match, built from the
shapes the user actually bets.

  Favourite legs   double chance OR win, favourite to score, one high
                   match-goals under (4.5 / 5.5 / 6.5).
  Underdog legs    2+ shots on target, 7+ or 8+ shots, 2+ corners.

Rules (set by the user):
  * 2 to 5 legs, never two legs from the same slot (no under 4.5 + under 6.5,
    no double chance + win, no 7+ shots + 8+ shots).
  * The combined fair price must be at least MIN_FAIR (1.20). Below that the
    builder is "chalk". There is no upper cap on the price.
  * Within that, pick the combination with the HIGHEST combined chance.

The combined chance is measured on the correlated match simulation, never
multiplied from the legs. Every combination is tried (a few hundred), so this
is an exhaustive search, not a greedy guess.

Favourite and underdog are decided by the model's win probabilities. Goals,
results and double chance come from the goals model; shots and corners come
from team rates (form), so those legs carry more uncertainty and are marked.
"""

from dataclasses import dataclass, field
from itertools import product
from typing import Dict, List, Optional

import numpy as np

from engine.v2.goals import GoalPrediction
from engine.v2.sim import Sim

MIN_LEGS = 2
MAX_LEGS = 5
MIN_FAIR = 1.20
MAX_JOINT = 1.0 / MIN_FAIR
# in a 3+ leg builder every leg must lower the chance by at least this much,
# otherwise it is padding (a leg that is almost certain adds nothing)
MATTER = 0.005
# combinations within this chance of the best count as tied; ties go to the one
# that leans on fewer form-based legs, then fewer legs, then the higher price
TIE = 0.005

UNDER_LINES = (4.5, 5.5, 6.5)


@dataclass
class Shape:
    label: str
    prob: float
    side: str            # "favourite" | "underdog"
    source: str          # "model" | "form"
    slot: str = ""       # legs in the same slot can never be combined
    mask: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    @property
    def fair(self) -> float:
        return 1.0 / self.prob if self.prob > 0 else 999.0

    def to_dict(self) -> dict:
        return {"label": self.label, "prob": round(self.prob, 4),
                "fair": round(self.fair, 2), "side": self.side, "source": self.source}


@dataclass
class Builder:
    legs: List[Shape]
    joint: float
    floor_met: bool = True   # False only if no combination reached the price floor

    @property
    def fair(self) -> float:
        return 1.0 / self.joint if self.joint > 0 else 999.0

    @property
    def form_legs(self) -> int:
        return sum(1 for l in self.legs if l.source != "model")

    def to_dict(self) -> dict:
        return {"joint": round(self.joint, 4), "fair": round(self.fair, 2),
                "floor_met": self.floor_met, "legs": [l.to_dict() for l in self.legs]}


def _joint(sim: Sim, legs: List[Shape]) -> float:
    return sim.joint([l.mask for l in legs])


def _all_matter(sim: Sim, legs: List[Shape], joint: float) -> bool:
    if len(legs) < 3:
        return True
    for i in range(len(legs)):
        if _joint(sim, legs[:i] + legs[i + 1:]) - joint < MATTER:
            return False
    return True


def _redundant(legs: List[Shape]) -> bool:
    # a win already contains "to score"
    slots = {l.slot: l for l in legs}
    return "result" in slots and slots["result"].label.endswith("to win") and "score" in slots


def choose(sim: Sim, slots: List[List[Shape]]) -> Optional[Builder]:
    """Best legal combination: highest chance with fair price >= MIN_FAIR."""
    combos = []
    for pick in product(*[[None] + opts for opts in slots]):
        legs = [x for x in pick if x is not None]
        if not (MIN_LEGS <= len(legs) <= MAX_LEGS) or _redundant(legs):
            continue
        combos.append((_joint(sim, legs), legs))
    if not combos:
        return None
    combos.sort(key=lambda c: -c[0])

    feasible = [c for c in combos if 0 < c[0] <= MAX_JOINT + 1e-12]
    for pool_source, floor_met in ((feasible, True), (combos, False)):
        ok = [c for c in pool_source if _all_matter(sim, c[1], c[0])]
        if not ok:
            ok = pool_source
        if not ok:
            continue
        if floor_met:
            top = ok[0][0]
            tied = [c for c in ok if c[0] >= top - TIE]
            j, legs = min(tied, key=lambda c: (sum(1 for l in c[1] if l.source != "model"),
                                               len(c[1]), -(1.0 / c[0])))
        else:
            # nothing reaches the floor: take the highest price available
            j, legs = min(ok, key=lambda c: c[0])
        return Builder(legs, j, floor_met)
    return None


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

    def leg(label, mask, side, source, slot) -> Shape:
        return Shape(label, sim.probability(mask), side, source, slot, mask)

    slots: List[List[Shape]] = [
        [leg(f"{fav} double chance", fg >= dg, "favourite", "model", "result"),
         leg(f"{fav} to win", fg > dg, "favourite", "model", "result")],
        [leg(f"{fav} to score", fg >= 1, "favourite", "model", "score")],
        [leg(f"Under {ln:g} goals", total <= ln, "favourite", "model", "total")
         for ln in UNDER_LINES],
    ]
    if include_underdog:
        t = sim.column("t_a" if fav_home else "t_h")
        s = sim.column("s_a" if fav_home else "s_h")
        c = sim.column("c_a" if fav_home else "c_h")
        slots += [
            [leg(f"{dog} 2+ shots on target", t >= 2, "underdog", "form", "sot")],
            [leg(f"{dog} 7+ shots", s >= 7, "underdog", "form", "shots"),
             leg(f"{dog} 8+ shots", s >= 8, "underdog", "form", "shots")],
            [leg(f"{dog} 2+ corners", c >= 2, "underdog", "form", "corners")],
        ]

    pick = choose(sim, slots)
    return {
        "favourite": fav, "underdog": dog,
        "fav_win_prob": float(r["H"] if fav_home else r["A"]),
        "underdog_shown": include_underdog,
        "pick": pick,
    }
