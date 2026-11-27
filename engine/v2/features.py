"""
engine/v2/features.py

Team strength from recent matches, with three signals:

  goals     the target: what actually went in
  xG        the better estimator of underlying performance (where available)
  shots / shots on target / corners / cards
            the secondary markets; these never enter the 1X2/goals model,
            they only feed the form notes and the same-game builder

All averages are time-decayed and shrunk toward the league average, and only
matches strictly BEFORE the fixture date are ever used.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np

from engine.data.model import Match
from engine.data.store import Store

LEAGUES = ["epl", "la_liga", "bundesliga", "serie_a", "ligue_1"]
LEAGUE_NAMES = {"epl": "Premier League", "la_liga": "La Liga", "bundesliga": "Bundesliga",
                "serie_a": "Serie A", "ligue_1": "Ligue 1"}

STAT_COLS = {
    "goals": ("ft_h", "ft_a"),
    "xg": ("xg_h", "xg_a"),
    "shots": ("sh_h", "sh_a"),
    "sot": ("sot_h", "sot_a"),
    "corners": ("co_h", "co_a"),
    "cards": ("yc_h", "yc_a"),
}

HALF_LIFE_DAYS = 150.0      # a match this old counts half as much
PRIOR_GAMES = 6.0           # shrink a team's rate toward the league average
MIN_GAMES = 3
LOOKBACK_DAYS = 730


@dataclass
class StatLine:
    home: float
    away: float


class TeamBook:
    def __init__(self, matches_by_league: Dict[str, List[Match]], xg_snapshot=None):
        self.raw = {lg: sorted(ms, key=lambda m: m.date) for lg, ms in matches_by_league.items()}
        # optional weekly xG ratings: (league, team, venue, kind) -> (value, n)
        self.xg_snapshot = xg_snapshot or {}
        self.by_team: Dict[str, Dict[str, List[Match]]] = {}
        for lg, ms in self.raw.items():
            idx = defaultdict(list)
            for m in ms:
                idx[m.home].append(m)
                idx[m.away].append(m)
            self.by_team[lg] = idx
        self._means = {}
        self._rates = {}

    @classmethod
    def from_dir(cls, data_dir: str, leagues=None, xg_snapshot=None) -> "TeamBook":
        data = {}
        for lg in (leagues or LEAGUES):
            path = f"{data_dir}/{lg}.csv"
            st = Store(lg, path)
            st.load()
            data[lg] = st.rows
        return cls(data, xg_snapshot=xg_snapshot)

    def teams(self, league: str):
        return set(self.by_team.get(league, {}))

    def last_date(self, league: str) -> Optional[date]:
        ms = [m for m in self.raw.get(league, []) if m.finished]
        return max((m.date for m in ms), default=None)

    # ---- league baselines -------------------------------------------------
    def league_means(self, league: str, as_of: date) -> Dict[str, StatLine]:
        key = (league, as_of)
        if key in self._means:
            return self._means[key]
        floor = as_of - timedelta(days=LOOKBACK_DAYS)
        ms = [m for m in self.raw.get(league, []) if m.finished and floor <= m.date < as_of]
        out = {}
        for stat, (fh, fa) in STAT_COLS.items():
            hs = [getattr(m, fh) for m in ms if getattr(m, fh) is not None]
            as_ = [getattr(m, fa) for m in ms if getattr(m, fa) is not None]
            # fall back to the whole available history if the window is empty
            if not hs:
                hs = [getattr(m, fh) for m in self.raw[league] if getattr(m, fh) is not None]
                as_ = [getattr(m, fa) for m in self.raw[league] if getattr(m, fa) is not None]
            out[stat] = StatLine(float(np.mean(hs)) if hs else 1.0,
                                 float(np.mean(as_)) if as_ else 1.0)
        self._means[key] = out
        return out

    # ---- one team's rate --------------------------------------------------
    def _games(self, league: str, team: str, as_of: date):
        return [m for m in self.by_team.get(league, {}).get(team, []) if m.date < as_of]

    def sample(self, league: str, team: str, stat: str, as_of: date) -> int:
        if stat == "xg" and self.xg_snapshot:
            n = 0
            for venue in ("home", "away"):
                for kind in ("for", "against"):
                    _, sn = self.xg_snapshot.get((league, team, venue, kind), (None, 0))
                    n = max(n, sn)
            if n:
                return n
        fh, fa = STAT_COLS[stat]
        n = 0
        for m in self._games(league, team, as_of):
            if getattr(m, fh) is not None and getattr(m, fa) is not None:
                n += 1
        return n

    def rate(self, league: str, team: str, stat: str, venue: str, kind: str,
             as_of: date) -> Optional[float]:
        """Weighted, shrunk per-match rate. venue 'home'/'away'/None; kind 'for'/'against'."""
        if stat == "xg" and self.xg_snapshot and venue:
            hit = self.xg_snapshot.get((league, team, venue, kind))
            if hit and hit[0] is not None:
                return hit[0]
        key = (league, team, stat, venue, kind, as_of)
        if key in self._rates:
            return self._rates[key]
        fh, fa = STAT_COLS[stat]
        lg = self.league_means(league, as_of)[stat]
        base = lg.home if venue in ("home", None) else lg.away
        # For "against" the relevant league baseline is what the opponent produced
        # at this venue; use the opposite side's average.
        if kind == "against":
            base = lg.away if venue == "home" else lg.home if venue == "away" else (lg.home + lg.away) / 2
        num = den = 0.0
        for m in self._games(league, team, as_of):
            side = "home" if m.home == team else "away"
            if venue and side != venue:
                continue
            h, a = getattr(m, fh), getattr(m, fa)
            if h is None or a is None:
                continue
            x = h if side == "home" else a
            if kind == "against":
                x = a if side == "home" else h
            w = 0.5 ** ((as_of - m.date).days / HALF_LIFE_DAYS)
            num += w * x
            den += w
        if den == 0:
            return None
        return (num + PRIOR_GAMES * base) / (den + PRIOR_GAMES)

    # ---- expected stats for one fixture -----------------------------------
    def expected(self, league: str, home: str, away: str, as_of: date) -> Dict[str, StatLine]:
        lg = self.league_means(league, as_of)
        out = {}
        for stat in STAT_COLS:
            h = self._expected_side(league, home, away, stat, "home", as_of, lg)
            a = self._expected_side(league, away, home, stat, "away", as_of, lg)
            if h is not None and a is not None:
                out[stat] = StatLine(h, a)
        return out

    def _expected_side(self, league, team, opp, stat, venue, as_of, lg) -> Optional[float]:
        if self.sample(league, team, stat, as_of) < MIN_GAMES:
            return None
        att = self.rate(league, team, stat, venue, "for", as_of)
        dfn = self.rate(league, opp, stat, "away" if venue == "home" else "home", "against", as_of)
        base = lg[stat].home if venue == "home" else lg[stat].away
        if att is None or dfn is None or base <= 0:
            return None
        base_att = lg[stat].home if venue == "home" else lg[stat].away
        base_dfn = lg[stat].away if venue == "home" else lg[stat].home
        if base_att <= 0 or base_dfn <= 0:
            return None
        return base * (att / base_att) * (dfn / base_dfn)

    # ---- form ------------------------------------------------------------
    def points(self, league: str, team: str, as_of: date, n: int = 5) -> List[int]:
        pts = []
        for m in reversed(self._games(league, team, as_of)):
            if not m.finished:
                continue
            if m.home == team:
                gf, ga = m.ft_h, m.ft_a
            else:
                gf, ga = m.ft_a, m.ft_h
            pts.append(3 if gf > ga else 1 if gf == ga else 0)
            if len(pts) == n:
                break
        return pts
