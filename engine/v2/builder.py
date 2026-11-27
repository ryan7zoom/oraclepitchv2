"""
engine/v2/builder.py

The same-game builder.

Legs come from two places:
  * the goals model: result, double chance, BTTS, match totals, team totals
  * form: corners, shots, shots on target, cards, most corners/cards

The joint probability is always measured on the correlated simulation, never
multiplied. Legs are chosen greedily to maximise that joint probability under
diversity and conflict constraints, so the builder is a real constrained
search rather than "take the five shortest prices".
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from engine.v2.form import FormCandidate
from engine.v2.goals import GoalPrediction
from engine.v2.markets import Market
from engine.v2.sim import Sim

MODEL_GROUPS = {"res:H": "result", "res:D": "result", "res:A": "result",
                "dc:1X": "result", "dc:X2": "result", "dc:12": "result",
                "btts:Y": "btts", "btts:N": "btts"}

GROUP_NAMES = {
    "result": "result", "btts": "btts", "goals": "total goals",
    "team_goals": "team goals", "corners": "corners", "shots": "shots",
    "sot": "shots on target", "cards": "cards",
    "most_corners": "most corners", "most_cards": "most cards",
}


@dataclass
class Leg:
    key: str
    label: str
    group: str
    kind: str                 # result | dc | btts | total | team | corners | shots | sot | cards | most
    side: str
    line: Optional[float]
    prob: float
    source: str               # model | form
    hit: Optional[int] = None
    window: Optional[int] = None
    team: str = ""
    form_cand: Optional[FormCandidate] = field(default=None, repr=False, compare=False)
    _mask: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    @property
    def hit_text(self) -> str:
        return f"{self.hit}/{self.window}" if self.hit and self.window else ""

    @property
    def fair(self) -> float:
        return 1.0 / self.prob if self.prob > 0 else 999.0

    def mask(self, sim: Sim) -> np.ndarray:
        if self._mask is not None:
            return self._mask
        if self.form_cand is not None:
            self._mask = self.form_cand.mask(sim)
            return self._mask
        gh, ga = sim.column("g_h"), sim.column("g_a")
        if self.kind == "result":
            m = {"H": gh > ga, "D": gh == ga, "A": gh < ga}[self.side]
        elif self.kind == "dc":
            m = {"1X": gh >= ga, "X2": ga >= gh, "12": gh != ga}[self.side]
        elif self.kind == "btts":
            both = (gh > 0) & (ga > 0)
            m = both if self.side == "Y" else ~both
        elif self.kind == "total":
            v = gh + ga
            m = v > self.line if self.side == "over" else v <= self.line
        elif self.kind == "team":
            v = gh if self.side.startswith("home") else ga
            m = v > self.line if self.side.endswith("over") else v <= self.line
        elif self.kind == "most":
            if self.side in ("home", "away"):
                a = gh if self.side == "home" else ga
                b = ga if self.side == "home" else gh
                m = a > b
            else:
                m = np.zeros(len(sim), dtype=bool)
        else:
            m = np.zeros(len(sim), dtype=bool)
        self._mask = m
        return m


@dataclass
class Slip:
    legs: List[Leg]
    joint: float
    product: float

    @property
    def fair(self) -> float:
        return 1.0 / self.joint if self.joint > 0 else 999.0

    @property
    def model_legs(self) -> int:
        return sum(1 for l in self.legs if l.source == "model")

    def to_dict(self):
        return {
            "joint": round(self.joint, 4),
            "fair": round(self.fair, 2),
            "legs": [{"label": l.label, "prob": round(l.prob, 4), "source": l.source,
                      "hit": l.hit_text, "group": l.group} for l in self.legs],
        }


def _model_legs(pred: GoalPrediction, markets: Sequence[Market]) -> List[Leg]:
    out = []
    for m in markets:
        if m.kind == "handicap":
            continue
        if m.kind in ("result", "dc", "btts"):
            group = "result" if m.kind in ("result", "dc") else "btts"
        elif m.kind == "total":
            group = "goals"
        elif m.kind == "team":
            group = "team_goals"
        else:
            continue
        if not (0.55 <= m.prob <= 0.90):
            continue
        out.append(Leg(m.key, m.label, group, m.kind, m.side, m.line, m.prob, "model"))
    return out


def _form_legs(cands: Sequence[FormCandidate]) -> List[Leg]:
    out = []
    for c in cands:
        if c.rate < 0.70 or not (0.52 <= c.prob <= 0.92):
            continue
        group = {"corners": "corners", "shots": "shots", "sot": "sot",
                 "cards": "cards"}[c.stat]
        out.append(Leg(c.key, c.label, group, c.stat, c.direction, c.line,
                       c.prob, "form", c.hits, c.window, c.team, form_cand=c))
    return out


def _most_legs(sim: Sim, home: str, away: str) -> List[Leg]:
    out = []
    for kind, ch, ca, label in (("most_corners", "c_h", "c_a", "most corners"),
                                ("most_cards", "yc_h", "yc_a", "most cards")):
        a, b = sim.column(ch), sim.column(ca)
        ph, pa = float((a > b).mean()), float((b > a).mean())
        for side, p, name in (("home", ph, home), ("away", pa, away)):
            if 0.55 <= p <= 0.85:
                out.append(Leg(f"most:{kind}:{side}", f"{name} {label}", kind,
                               "most", side, None, p, "form"))
    return out


def _conflict(a: Leg, b: Leg) -> bool:
    if a.group == b.group:
        return True
    if {a.group, b.group} == {"result", "result"}:
        return True
    # a total under a line cannot coexist with a team over a line at or above it
    for x, y in ((a, b), (b, a)):
        if x.kind == "total" and x.side == "under" and y.kind == "team" and y.side.endswith("over"):
            if y.line >= x.line:
                return True
    # BTTS no cannot coexist with both teams scoring; a single team over 0.5 is still possible
    if a.kind == "btts" and b.kind == "btts" and a.side != b.side:
        return True
    return False


def _joint(sim: Sim, legs: Sequence[Leg]) -> float:
    return sim.joint([l.mask(sim) for l in legs])


def _greedy(sim: Sim, candidates: List[Leg], max_legs: int) -> Slip:
    chosen: List[Leg] = []
    used_groups = set()
    while len(chosen) < max_legs:
        best, best_joint = None, -1.0
        for c in candidates:
            if c.group in used_groups:
                continue
            if any(_conflict(c, x) for x in chosen):
                continue
            j = _joint(sim, chosen + [c])
            if j > best_joint:
                best, best_joint = c, j
        if best is None:
            break
        chosen.append(best)
        used_groups.add(best.group)
    joint = _joint(sim, chosen) if chosen else 0.0
    product = float(np.prod([l.prob for l in chosen])) if chosen else 0.0
    return Slip(chosen, joint, product)


def build(pred: GoalPrediction, markets: Sequence[Market], form_cands: Sequence[FormCandidate],
          sim: Sim, max_legs: int = 5) -> Dict[str, object]:
    """Return the best slip plus a safer alternative."""
    cands = _model_legs(pred, markets) + _form_legs(form_cands) + _most_legs(sim, pred.home, pred.away)
    # de-duplicate keys, keep the best probability
    by_key: Dict[str, Leg] = {}
    for c in cands:
        if c.key not in by_key or c.prob > by_key[c.key].prob:
            by_key[c.key] = c
    cands = list(by_key.values())

    safe = _greedy(sim, cands, 3)
    best = _greedy(sim, cands, max_legs)
    # a five-leg slip should only be preferred when it still has a realistic chance
    if len(best.legs) > 4 and best.joint < 0.20 and len(safe.legs) >= 3:
        best = _greedy(sim, cands, 4)
    return {"best": best, "safe": safe}
