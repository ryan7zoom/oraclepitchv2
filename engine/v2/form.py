"""
engine/v2/form.py

Historical hit rates for the markets the goals model does not predict:
corners, shots, shots on target and cards.

These are deliberately NOT probabilities from the model. They are shown as
"9/10" form notes under the prediction and can be used as same-game builder
legs, but they never change the 1X2/goals numbers.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence

import numpy as np

from engine.v2.features import TeamBook
from engine.v2.sim import Sim

TARGET_RATE = 0.80
MIN_RATE = 0.70
MAX_UNDER_RATE = 0.85       # don't show a 15/15 Under as a trend
MIN_GAMES = 8
WINDOWS = (15, 12, 10, 8)

# A ladder is generated around THIS match's expected count, not a universal
# floor. Match totals sit near the expected total; team totals sit near that
# team's expected count. The low factor is deliberately close to the mean so
# a 25-shot match does not get a 19.5 line.
LADDER_FACTORS = {
    ("shots", "total"): (0.96, 1.20),
    ("shots", "team"): (0.80, 1.30),
    ("sot", "total"): (1.00, 1.40),
    ("sot", "team"): (0.75, 1.50),
    ("corners", "total"): (0.90, 1.30),
    ("corners", "team"): (0.80, 1.55),
    ("cards", "total"): (0.60, 1.50),
    ("cards", "team"): (0.60, 1.60),
}


def ladder(center: float, stat: str, subject: str) -> List[float]:
    """Half-goal lines around the expected count for this fixture/team."""
    kind = "total" if subject == "total" else "team"
    lo_f, hi_f = LADDER_FACTORS[(stat, kind)]
    center = max(1.0, center)
    start = max(0.5, math.floor(center * lo_f) + 0.5)
    if stat == "sot" and subject == "total":
        start = max(8.5, start)      # the book's match-SOT ladder starts at 8.5
    end = max(start + 3.0, math.ceil(center * hi_f) + 0.5)
    n = int(round((end - start) / 0.5)) + 1
    return [start + 0.5 * i for i in range(n)]


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


def _best(values: Sequence[float], lines: Sequence[float], direction: str):
    """The line a bookmaker actually offers, chosen for a useful hit rate.

    Over:  the lowest line that clears 70% (bookmaker ladder starts at 24.5 /
           8.5 for match shots / SOT, so we never show 19.5 or 5.5).
    Under: the highest line that still clears 70% but does not become pure
           chalk (e.g. Under 13.5, not Under 15.5 at 15/15).
    If nothing clears the filter, show the closest bookmaker line anyway.
    """
    n = len(values)
    if n < MIN_GAMES:
        return None
    ordered = sorted(lines) if direction == "over" else sorted(lines, reverse=True)
    fallback = None
    for line in ordered:
        hits = sum(1 for v in values if (v > line if direction == "over" else v <= line))
        rate = hits / n
        if rate < MIN_RATE or (direction == "under" and rate > MAX_UNDER_RATE):
            if direction == "under" and rate > MAX_UNDER_RATE:
                continue
            if fallback is None or abs(rate - TARGET_RATE) < abs(fallback[0] - TARGET_RATE):
                w = min(10, n)
                hw = sum(1 for v in values[:w] if (v > line if direction == "over" else v <= line))
                fallback = (rate, line, hw, w)
            continue
        win = None
        for w in WINDOWS:
            if w > n:
                continue
            hw = sum(1 for v in values[:w] if (v > line if direction == "over" else v <= line))
            if hw / w >= MIN_RATE:
                win = (hw, w, hw / w)
                break
        if win is not None:
            if direction == "over" or win[2] <= MAX_UNDER_RATE:
                return line, direction, win[0], win[1], win[2]
            continue
        if direction == "under":
            continue
        if fallback is None or abs(rate - TARGET_RATE) < abs(fallback[0] - TARGET_RATE):
            w = min(10, n)
            hw = sum(1 for v in values[:w] if (v > line if direction == "over" else v <= line))
            fallback = (rate, line, hw, w)
    if direction == "under":
        return None
    if fallback is not None:
        _, line, hits, window = fallback
        return line, direction, hits, window, hits / window
    return None


def _means(sim: Sim) -> Dict[str, Dict[str, float]]:
    out = {}
    for stat, (h, a) in {"corners": ("c_h", "c_a"), "shots": ("s_h", "s_a"),
                         "sot": ("t_h", "t_a"), "cards": ("yc_h", "yc_a")}.items():
        hv, av = sim.column(h), sim.column(a)
        out[stat] = {"home": float(hv.mean()), "away": float(av.mean()),
                     "total": float((hv + av).mean())}
    return out


def candidates(book: TeamBook, league: str, home: str, away: str, as_of: date,
               sim: Sim) -> List[FormCandidate]:
    """Every qualifying form note for one fixture, with simulated probability."""
    out = []
    means = _means(sim)
    specs = [
        ("corners", "home", home, ("over", "under")),
        ("corners", "away", away, ("over", "under")),
        ("corners", "total", "", ("over", "under")),
        ("shots", "home", home, ("over",)),
        ("shots", "away", away, ("over",)),
        ("shots", "total", "", ("over",)),
        ("sot", "home", home, ("over",)),
        ("sot", "away", away, ("over",)),
        ("sot", "total", "", ("over",)),
        ("cards", "total", "", ("over", "under")),
        ("cards", "home", home, ("over", "under")),
        ("cards", "away", away, ("over", "under")),
    ]
    for stat, subject, team, directions in specs:
        if subject == "total":
            vals = _total_values(book, league, home, away, stat, as_of)
        else:
            vals = _values(book, league, team, stat, as_of, subject)
        lines = ladder(means[stat][subject], stat, subject)
        # for total, values are one per match the two teams played separately; this is
        # only a rough form sample. Use matches in the league involving either side.
        for direction in directions:
            best = _best(vals, lines, direction)
            if not best:
                continue
            line, direction, hits, window, rate = best
            name = team if subject != "total" else "Match"
            label_stat = {"corners": "corners", "shots": "shots", "sot": "shots on target",
                          "cards": "cards"}[stat]
            if subject == "total":
                label = f"Match total {label_stat} {direction} {line:g}"
            else:
                label = f"{name} team {label_stat} {direction} {line:g}"
            c = FormCandidate(stat, subject, direction, line, hits, window, rate, 0.0,
                              label, team)
            c.prob = sim.probability(c.mask(sim))
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


def grouped(book: TeamBook, league: str, home: str, away: str, as_of: date,
            sim: Sim):
    """(team form, match form), each line already labelled with its scope."""
    cs = candidates(book, league, home, away, as_of, sim)
    team, match = {}, {}
    for c in cs:
        if c.subject == "total":
            match.setdefault(c.stat, c)
        elif c.stat == "corners":
            team.setdefault((c.subject, c.stat, c.direction), c)
        else:
            team.setdefault((c.subject, c.stat), c)
    order = {"home": 0, "away": 1}
    stat_order = {"corners": 0, "shots": 1, "sot": 2, "cards": 3}
    team_list = sorted(team.values(), key=lambda c: (order.get(c.subject, 9),
                                                     stat_order.get(c.stat, 9),
                                                     c.direction))
    match_list = sorted(match.values(), key=lambda c: stat_order.get(c.stat, 9))
    return team_list, match_list


def notes(book: TeamBook, league: str, home: str, away: str, as_of: date,
          sim: Sim, limit: int = 12) -> List[FormCandidate]:
    team, match = grouped(book, league, home, away, as_of, sim)
    return (team + match)[:limit]
