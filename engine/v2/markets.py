"""
engine/v2/markets.py

The model-backed market catalogue: result, double chance, both teams to
score, match totals, team totals, and (for display only, at the bottom of a
match card) Asian handicaps. No corners/shots/cards here: those are form
notes and builder legs, not part of the 1X2/goals model.
"""

from dataclasses import dataclass
from typing import List, Optional

from engine.v2.goals import GoalPrediction

TOTAL_LINES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5]
TEAM_LINES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
HANDICAP_LINES = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]


@dataclass
class Market:
    key: str
    label: str
    group: str
    kind: str             # result | dc | btts | total | team | handicap
    side: str             # H/D/A, Y/N, over/under, home/away
    line: Optional[float]
    prob: float

    @property
    def fair(self) -> float:
        return 1.0 / self.prob if self.prob > 0 else 999.0


def _result_markets(pred: GoalPrediction) -> List[Market]:
    r = pred.result()
    return [
        Market("res:H", f"{pred.home} win", "result", "result", "H", None, r["H"]),
        Market("res:D", "Draw", "result", "result", "D", None, r["D"]),
        Market("res:A", f"{pred.away} win", "result", "result", "A", None, r["A"]),
    ]


def _dc_markets(pred: GoalPrediction) -> List[Market]:
    d = pred.double_chance()
    return [
        Market("dc:1X", f"{pred.home} or draw", "double_chance", "dc", "1X", None, d["1X"]),
        Market("dc:X2", f"{pred.away} or draw", "double_chance", "dc", "X2", None, d["X2"]),
        Market("dc:12", "No draw", "double_chance", "dc", "12", None, d["12"]),
    ]


def _btts_markets(pred: GoalPrediction) -> List[Market]:
    b = pred.btts()
    return [
        Market("btts:Y", "Both teams score", "btts", "btts", "Y", None, b["Y"]),
        Market("btts:N", "Not both teams score", "btts", "btts", "N", None, b["N"]),
    ]


def _total_markets(pred: GoalPrediction) -> List[Market]:
    out = []
    for line in TOTAL_LINES:
        over = pred.total_over(line)
        out.append(Market(f"tot:O{line}", f"Over {line:g} goals", "goals", "total", "over", line, over))
        out.append(Market(f"tot:U{line}", f"Under {line:g} goals", "goals", "total", "under", line, 1 - over))
    return out


def _team_markets(pred: GoalPrediction) -> List[Market]:
    out = []
    for side, name in (("home", pred.home), ("away", pred.away)):
        for line in TEAM_LINES:
            over = pred.team_over(side, line)
            out.append(Market(f"{side}:O{line}", f"{name} over {line:g} goals", "team_goals",
                              "team", f"{side}:over", line, over))
            out.append(Market(f"{side}:U{line}", f"{name} under {line:g} goals", "team_goals",
                              "team", f"{side}:under", line, 1 - over))
    return out


def _handicap_markets(pred: GoalPrediction) -> List[Market]:
    out = []
    for line in HANDICAP_LINES:
        h = pred.handicap("home", line)
        a = pred.handicap("away", -line)
        out.append(Market(f"ah:H{line:+g}", f"{pred.home} {line:+g}", "handicap",
                          "handicap", "home", line, h))
        out.append(Market(f"ah:A{-line:+g}", f"{pred.away} {-line:+g}", "handicap",
                          "handicap", "away", -line, a))
    return out


def build(pred: GoalPrediction) -> List[Market]:
    return (_result_markets(pred) + _dc_markets(pred) + _btts_markets(pred)
            + _total_markets(pred) + _team_markets(pred) + _handicap_markets(pred))


def main_total(pred: GoalPrediction) -> Market:
    ms = _total_markets(pred)
    over = min((m for m in ms if m.side == "over"), key=lambda m: abs(m.prob - 0.5))
    under = next(m for m in ms if m.side == "under" and m.line == over.line)
    return over if over.prob >= 0.5 else under


def main_handicap(pred: GoalPrediction) -> Market:
    ms = _handicap_markets(pred)
    return min(ms, key=lambda m: abs(m.prob - 0.5))


def outcome_label(pred: GoalPrediction) -> str:
    r = pred.result()
    best = max(r, key=r.get)
    return {"H": f"{pred.home} win", "D": "Draw", "A": f"{pred.away} win"}[best]
