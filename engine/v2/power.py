"""
engine/v2/power.py

Club strength as a single, cross-team number.

Primary source: ClubElo (free, daily European club Elo). We read a local
snapshot if present, otherwise the current ranking page. For historical
backtests ClubElo has no free as-of API, so we fall back to an Elo table
computed from the match history we already have.

The Elo difference is converted to an expected goal supremacy by a slope
fitted on recent matches, so the rating is a prior in goal units rather than
a separate prediction.
"""

import difflib
import math
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

import numpy as np

from engine.v2.features import LEAGUES, TeamBook

POWER_DIR = "data/power"
CLUBELO_FILE = os.path.join(POWER_DIR, "clubelo.csv")

HOME_ADV_ELO = 60.0
K_BASE = 20.0
DEFAULT_SLOPE = 0.35       # goals per 100 Elo
DEFAULT_HFA = 0.25         # goals

ALIASES = {
    "man united": "man united", "man utd": "man united",
    "man city": "man city", "newcastle": "newcastle",
    "tottenham": "tottenham", "nott'm forest": "forest",
    "nottingham forest": "forest", "ath madrid": "atletico",
    "atletico madrid": "atletico", "ath bilbao": "athletic club",
    "athletic bilbao": "athletic club", "celta": "celta",
    "sociedad": "real sociedad", "betis": "betis", "espanol": "espanyol",
    "alaves": "alaves", "paris sg": "paris sg",
    "paris saint-germain": "paris sg", "paris fc": "paris fc",
    "dortmund": "dortmund", "borussia dortmund": "dortmund",
    "m'gladbach": "gladbach", "borussia monchengladbach": "gladbach",
    "leverkusen": "leverkusen", "bayer leverkusen": "leverkusen",
    "ein frankfurt": "frankfurt", "eintracht frankfurt": "frankfurt",
    "fc koln": "koln", "koln": "koln", "st pauli": "st pauli",
    "hertha": "hertha", "milan": "milan", "ac milan": "milan",
    "inter": "internazionale", "inter milan": "internazionale",
    "verona": "verona", "hellas verona": "verona", "rome": "roma",
    "lazio": "lazio", "napoli": "napoli", "juventus": "juventus",
    "fiorentina": "fiorentina", "atalanta": "atalanta", "bologna": "bologna",
    "torino": "torino", "udinese": "udinese", "genoa": "genoa",
    "monaco": "monaco", "lyon": "lyon", "lille": "lille",
    "marseille": "marseille", "lens": "lens", "rennes": "rennes",
    "nice": "nice", "brest": "brest", "toulouse": "toulouse",
    "nantes": "nantes", "strasbourg": "strasbourg", "reims": "reims",
    "auxerre": "auxerre", "le havre": "le havre", "werder bremen": "werder",
    "werder": "werder", "wolves": "wolves",
}


def _decode(s: str) -> str:
    if "\\u" in s:
        try:
            return s.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception:
            return s
    return s


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", "and").replace(".", "").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class ClubElo:
    """A snapshot of ClubElo ratings, keyed by canonical-ish club name."""

    def __init__(self, ratings: Dict[str, float], as_of: date, source: str):
        self.ratings = ratings
        self.as_of = as_of
        self.source = source
        self._names = list(ratings)
        self._alias = {_norm(k): _norm(v) for k, v in ALIASES.items()}
        self._cache = {}

    def get(self, team: str) -> Optional[float]:
        if team in self._cache:
            return self._cache[team]
        raw = _norm(team)
        keys = [raw]
        alias = self._alias.get(raw)
        if alias and alias != raw:
            keys.append(alias)
        for key in keys:
            if key in self.ratings:
                self._cache[team] = self.ratings[key]
                return self._cache[team]
        # a little fuzzy matching; never invent a rating for a clearly different club
        for key in keys:
            match = difflib.get_close_matches(key, self._names, n=1, cutoff=0.84)
            if match:
                self._cache[team] = self.ratings[match[0]]
                return self._cache[team]
        self._cache[team] = None
        return None

    @classmethod
    def load(cls, path: str = CLUBELO_FILE) -> Optional["ClubElo"]:
        if not os.path.exists(path):
            return None
        ratings, as_of = {}, None
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 3:
                    continue
                if parts[0].lower() == "date":
                    continue
                try:
                    as_of = date.fromisoformat(parts[0])
                    ratings[_norm(_decode(parts[1]))] = float(parts[2])
                except ValueError:
                    continue
        if not ratings or as_of is None:
            return None
        return cls(ratings, as_of, "ClubElo")

    @classmethod
    def fetch(cls, path: str = CLUBELO_FILE) -> Optional["ClubElo"]:
        """Fetch the current ClubElo ranking page and cache a small CSV snapshot."""
        try:
            import requests
        except ImportError:
            return None
        try:
            r = requests.get("https://clubelo.com/Ranking", timeout=30,
                             headers={"User-Agent": "OraclePitch/2.0"})
            if r.status_code != 200:
                return None
            pairs = re.findall(r'"Elo":\s*([0-9.]+)[^{}]*?"Name":\s*"([^"]+)"', r.text)
            if not pairs:
                pairs = [(e, n) for n, e in re.findall(
                    r'"Name":\s*"([^"]+)"[^{}]*?"Elo":\s*([0-9.]+)', r.text)]
            ratings = {_norm(_decode(n)): float(e) for e, n in pairs}
            if not ratings:
                return None
            today = date.today()
            os.makedirs(POWER_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("date,name,elo\n")
                for name, elo in sorted(ratings.items()):
                    f.write(f"{today.isoformat()},{name},{elo:.1f}\n")
            return cls(ratings, today, "ClubElo")
        except Exception:
            return None


class LocalElo:
    """Elo computed from the match history, with pre-match ratings recorded."""

    def __init__(self, book: TeamBook):
        self.book = book
        self.history: Dict[str, list] = defaultdict(list)   # team -> [(date, rating)]
        self.records = []                                    # (date, h, a, rh, ra, gd)
        self.ratings: Dict[str, float] = {}
        self._build()

    def _build(self):
        ms = []
        for lg in LEAGUES:
            ms.extend(self.book.raw.get(lg, []))
        ms = [m for m in ms if m.finished]
        ms.sort(key=lambda m: (m.date, m.home))
        for m in ms:
            rh = self.ratings.get(m.home, 1500.0)
            ra = self.ratings.get(m.away, 1500.0)
            gd = m.ft_h - m.ft_a
            self.records.append((m.date, m.home, m.away, rh, ra, gd))
            exp = 1.0 / (1.0 + 10.0 ** (-((rh + HOME_ADV_ELO) - ra) / 400.0))
            score = 1.0 if gd > 0 else 0.5 if gd == 0 else 0.0
            mult = 1.0 + 0.5 * min(abs(gd), 3)
            delta = K_BASE * mult * (score - exp)
            self.ratings[m.home] = rh + delta
            self.ratings[m.away] = ra - delta
            self.history[m.home].append((m.date, self.ratings[m.home]))
            self.history[m.away].append((m.date, self.ratings[m.away]))

    def rating_as_of(self, team: str, as_of: date) -> Optional[float]:
        hist = self.history.get(team, [])
        out = 1500.0
        for d, r in hist:
            if d < as_of:
                out = r
            else:
                break
        return out if hist else None

    def fit_hfa_slope(self, as_of: date) -> Tuple[float, float]:
        floor = as_of - timedelta(days=730)
        xs, ys = [], []
        for d, h, a, rh, ra, gd in self.records:
            if floor <= d < as_of:
                xs.append((rh - ra) / 100.0)
                ys.append(gd)
        if len(xs) < 200:
            return DEFAULT_HFA, DEFAULT_SLOPE
        x = np.asarray(xs)
        y = np.asarray(ys)
        slope, intercept = np.polyfit(x, y, 1)
        return float(intercept), float(np.clip(slope, 0.10, 0.70))


# Leagues ClubElo does not cover reliably: always rated from their own results,
# so one league never mixes two rating scales.
LOCAL_ONLY_LEAGUES = {"saudi"}


class Power:
    def __init__(self, book: TeamBook, as_of: date, use_clubelo: bool = True,
                 auto_fetch: bool = True):
        self.book = book
        self.as_of = as_of
        self.local = LocalElo(book)
        self.clubelo = None
        if use_clubelo:
            self.clubelo = ClubElo.load()
            if self.clubelo and (self.clubelo.as_of > as_of
                                 or (as_of - self.clubelo.as_of).days > 21):
                self.clubelo = None
            if auto_fetch and self.clubelo is None:
                self.clubelo = ClubElo.fetch()
        self.hfa, self.slope = self.local.fit_hfa_slope(as_of)

    def rating(self, team: str, league: str) -> Optional[float]:
        if self.clubelo and league not in LOCAL_ONLY_LEAGUES:
            v = self.clubelo.get(team)
            if v is not None:
                return v
        return self.local.rating_as_of(team, self.as_of)

    @property
    def source(self) -> str:
        return self.clubelo.source if self.clubelo else "local Elo"

    def source_for(self, league: str) -> str:
        return "local Elo" if league in LOCAL_ONLY_LEAGUES else self.source

    def expected_supremacy(self, home: str, away: str, league: str) -> Optional[float]:
        rh, ra = self.rating(home, league), self.rating(away, league)
        if rh is None or ra is None:
            return None
        return self.hfa + self.slope * (rh - ra) / 100.0
