"""
engine/v2/fixtures.py

Upcoming top-five fixtures from ESPN's scoreboard, mapped onto the canonical
team names used by the match CSVs. A fixture with an unmapped team is skipped
and reported; names are never guessed.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from engine.data.espn import EspnClient
from engine.data.teams import TeamResolver
from engine.v2.features import LEAGUE_NAMES, LEAGUES

GMT8 = timezone(timedelta(hours=8))


@dataclass
class Fixture:
    league: str
    date: date
    home: str
    away: str
    kickoff: Optional[datetime] = None
    home_name: str = ""
    away_name: str = ""

    @property
    def key(self) -> str:
        return f"{self.league}:{self.date.isoformat()}:{self.home}:{self.away}"


def fetch(book, today: date, days: int = 3, budget: int = 80,
          now: Optional[datetime] = None) -> Tuple[List[Fixture], List[dict]]:
    now = now or datetime.now(timezone.utc)
    espn = EspnClient(budget=budget)
    out, skipped = [], []
    seen = set()
    for league in LEAGUES:
        resolver = TeamResolver(league, book.teams(league))
        try:
            for offset in range(-1, days + 2):
                d = today + timedelta(days=offset)
                for ev in espn.scoreboard(league, d):
                    if ev.id in seen or ev.completed or ev.kickoff is None:
                        continue
                    seen.add(ev.id)
                    ko = ev.kickoff.astimezone(GMT8)
                    if ko <= now.astimezone(GMT8) or not (today <= ko.date() <= today + timedelta(days=days)):
                        continue
                    home, away = resolver.resolve(ev.home_name), resolver.resolve(ev.away_name)
                    if not (home and away):
                        skipped.append({"league": league, "home": ev.home_name, "away": ev.away_name,
                                        "reason": "team name not matched"})
                        continue
                    out.append(Fixture(league, ko.date(), home, away, ko, ev.home_name, ev.away_name))
        except Exception as e:
            skipped.append({"league": league, "reason": f"ESPN fixtures unavailable: {e}"})
    out.sort(key=lambda f: (f.kickoff or datetime.max.replace(tzinfo=GMT8), f.league, f.home))
    return out, skipped


def from_json(path: str) -> List[Fixture]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for x in raw:
        ko = datetime.fromisoformat(x["kickoff"]) if x.get("kickoff") else None
        d = date.fromisoformat(x["date"]) if x.get("date") else (ko.date() if ko else date.today())
        out.append(Fixture(x["league"], d, x["home"], x["away"], ko,
                           x.get("home_name", x["home"]), x.get("away_name", x["away"])))
    return out


def to_json(fixtures: List[Fixture]) -> list:
    return [{"league": f.league, "date": f.date.isoformat(),
             "kickoff": f.kickoff.isoformat() if f.kickoff else None,
             "home": f.home, "away": f.away,
             "home_name": f.home_name, "away_name": f.away_name} for f in fixtures]


def league_name(league: str) -> str:
    return LEAGUE_NAMES.get(league, league)
