"""
engine/v2/form.py

Historical hit rates for the markets the goals model does not predict:
corners, shots, shots on target and cards.

These are deliberately NOT probabilities from the model. They are shown as
"9/10" form notes under the prediction and can be used as same-game builder
legs, but they never change the 1X2/goals numbers.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence

import numpy as np

from engine.v2.features import TeamBook
from engine.v2.sim import Sim

TARGET_RATE = 0.80
MIN_RATE = 0.70
MIN_GAMES = 8
WINDOWS = (15, 12, 10, 8)

TEAM_CORNERS = [x + 0.5 for x in range(2, 11)]
TOTAL_CORNERS = [x + 0.5 for x in range(8, 16)]
TEAM_SHOTS = [x + 0.5 for x in range(7, 22)]
TEAM_SOT = [x + 0.5 for x in range(1, 10)]
TOTAL_SHOTS = [x + 0.5 for x in range(16, 33)]
TOTAL_SOT = [x + 0.5 for x in range(5, 15)]
TOTAL_CARDS = [x + 0.5 for x in range(2, 6)]
TEAM_CARDS = [x + 0.5 for x in range(1, 5)]


@dataclass
class FormCandidate:
    stat: str                 # corners | shots | sot | cards
    subject: str              # home | away | total
    direction: str            # over | under
    line: float
    hits: int
    window: int
    rate: float
    prob: float               # simulated probability for THIS fixture
    label: str
    team: str

    @property
    def key(self) -> str:
        return f"form:{self.stat}:{self.subject}:{self.direction}:{self.line}"

    @property
    def hit_text(self) -> str:
        return f"{self.hits}/{self.window}"

    def mask(self, sim: Sim) -> np.ndarray:
        if self.stat == "corners":
            v = sim.column("c_h") if self.subject == "home" else (
                sim.column("c_a") if self.subject == "away" else
                sim.column("c_h") + sim.column("c_a"))
        elif self.stat == "shots":
            v = sim.column("s_h") if self.subject == "home" else (
                sim.column("s_a") if self.subject == "away" else
                sim.column("s_h") + sim.column("s_a"))
        elif self.stat == "sot":
            v = sim.column("t_h") if self.subject == "home" else (
                sim.column("t_a") if self.subject == "away" else
                sim.column("t_h") + sim.column("t_a"))
        else:
            v = sim.column("yc_h") if self.subject == "home" else (
                sim.column("yc_a") if self.subject == "away" else
                sim.column("yc_h") + sim.column("yc_a"))
        return v > self.line if self.direction == "over" else v <= self.line


def _values(book: TeamBook, league: str, team: str, stat: str, as_of: date,
            subject: str) -> List[float]:
    fh, fa = {"corners": ("co_h", "co_a"), "shots": ("sh_h", "sh_a"),
              "sot": ("sot_h", "sot_a"), "cards": ("yc_h", "yc_a")}[stat]
    out = []
    for m in reversed(book._games(league, team, as_of)):
        side = "home" if m.home == team else "away"
        h, a = getattr(m, fh), getattr(m, fa)
        if h is None or a is None:
            continue
        if subject == "home":
            if side == "home":
                out.append(h)
        elif subject == "away":
            if side == "away":
                out.append(a)
        else:
            out.append(h + a)
    return out


def _best(values: Sequence[float], lines: Sequence[float], directions: Sequence[str]):
    best = None
    n = len(values)
    if n < MIN_GAMES:
        return None
    for line in lines:
        for direction in directions:
            hits = sum(1 for v in values if (v > line if direction == "over" else v <= line))
            rate = hits / n
            if rate < MIN_RATE:
                continue
            # keep one fixed window: the longest one that still clears 70%
            win = None
            for w in WINDOWS:
                if w > n:
                    continue
                hw = sum(1 for v in values[:w] if (v > line if direction == "over" else v <= line))
                if hw / w >= MIN_RATE:
                    win = (hw, w, hw / w)
                    break
            if win is None:
                continue
            cand = (abs(win[2] - TARGET_RATE), win[2], win[1], line, direction, win[0])
            if best is None or cand < best:
                best = cand
    if best is None:
        return None
    _, rate, window, line, direction, hits = best
    return line, direction, hits, window, rate


def candidates(book: TeamBook, league: str, home: str, away: str, as_of: date,
               sim: Sim) -> List[FormCandidate]:
    """Every qualifying form note for one fixture, with simulated probability."""
    out = []
    specs = [
        ("corners", "home", home, TEAM_CORNERS, ("over", "under")),
        ("corners", "away", away, TEAM_CORNERS, ("over", "under")),
        ("corners", "total", "", TOTAL_CORNERS, ("over", "under")),
        ("shots", "home", home, TEAM_SHOTS, ("over",)),
        ("shots", "away", away, TEAM_SHOTS, ("over",)),
        ("shots", "total", "", TOTAL_SHOTS, ("over",)),
        ("sot", "home", home, TEAM_SOT, ("over",)),
        ("sot", "away", away, TEAM_SOT, ("over",)),
        ("sot", "total", "", TOTAL_SOT, ("over",)),
        ("cards", "total", "", TOTAL_CARDS, ("over", "under")),
        ("cards", "home", home, TEAM_CARDS, ("over", "under")),
        ("cards", "away", away, TEAM_CARDS, ("over", "under")),
    ]
    for stat, subject, team, lines, directions in specs:
        if subject == "total":
            vals = _total_values(book, league, home, away, stat, as_of)
        else:
            vals = _values(book, league, team, stat, as_of, subject)
        # for total, values are one per match the two teams played separately; this is
        # only a rough form sample. Use matches in the league involving either side.
        best = _best(vals, lines, directions)
        if not best:
            continue
        line, direction, hits, window, rate = best
        name = team if subject != "total" else "Match"
        label_stat = {"corners": "corners", "shots": "shots", "sot": "shots on target",
                      "cards": "cards"}[stat]
        if subject == "total":
            label = f"Match {label_stat} {direction} {line:g}"
        else:
            label = f"{name} {label_stat} {direction} {line:g}"
        c = FormCandidate(stat, subject, direction, line, hits, window, rate, 0.0,
                          label, team)
        c.prob = sim.probability(c.mask(sim))
        if 0.52 <= c.prob <= 0.94:
            out.append(c)
    # one candidate per (stat, subject, direction), best rate
    best_by = {}
    for c in out:
        k = (c.stat, c.subject, c.direction)
        if k not in best_by or c.rate > best_by[k].rate:
            best_by[k] = c
    return sorted(best_by.values(), key=lambda c: (-c.rate, -c.window, c.stat))


def _total_values(book: TeamBook, league: str, home: str, away: str,
                  stat: str, as_of: date) -> List[float]:
    """Total per match for the two teams' recent games, newest first, used only as a form sample."""
    fh, fa = {"corners": ("co_h", "co_a"), "shots": ("sh_h", "sh_a"),
              "sot": ("sot_h", "sot_a"), "cards": ("yc_h", "yc_a")}[stat]
    seen = {}
    for team in (home, away):
        for m in book._games(league, team, as_of):
            seen[id(m)] = m
    rows = sorted(seen.values(), key=lambda m: m.date, reverse=True)
    out = []
    for m in rows:
        h, a = getattr(m, fh), getattr(m, fa)
        if h is None or a is None:
            continue
        out.append(h + a)
    return out[:40]


def notes(book: TeamBook, league: str, home: str, away: str, as_of: date,
          sim: Sim, limit: int = 4) -> List[FormCandidate]:
    cs = candidates(book, league, home, away, as_of, sim)
    picked = []
    used = set()
    for c in cs:
        k = (c.stat, c.subject)
        if k in used:
            continue
        used.add(k)
        picked.append(c)
        if len(picked) == limit:
            break
    return picked
