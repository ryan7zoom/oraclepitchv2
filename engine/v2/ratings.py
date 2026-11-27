"""
engine/v2/ratings.py

Weekly rating snapshots.

ClubElo is cached in data/power/clubelo.csv by engine/v2/power.py. This module
adds the second weekly snapshot: team xG for/against rates, split by venue.

The daily model reads these snapshots; it does not rebuild them from the
day's match pull. That keeps the ratings on a weekly cadence while results,
odds and injuries still update every day.
"""

import csv
import os
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from engine.v2.features import LEAGUES, TeamBook

PATH = "data/power/xg.csv"
FIELDS = ["date", "league", "team", "venue", "kind", "value", "n"]


def _count(book: TeamBook, league: str, team: str, venue: str, as_of: date) -> int:
    n = 0
    for m in book._games(league, team, as_of):
        side = "home" if m.home == team else "away"
        if side != venue:
            continue
        if m.xg_h is not None and m.xg_a is not None:
            n += 1
    return n


def build(book: TeamBook, path: str = PATH) -> dict:
    dates = [book.last_date(lg) for lg in LEAGUES if book.last_date(lg)]
    as_of = (max(dates) + timedelta(days=1)) if dates else date.today()
    rows = []
    for lg in LEAGUES:
        for team in sorted(book.teams(lg)):
            for venue in ("home", "away"):
                n = _count(book, lg, team, venue, as_of)
                if n < 1:
                    continue
                for kind in ("for", "against"):
                    val = book.rate(lg, team, "xg", venue, kind, as_of)
                    if val is None:
                        continue
                    rows.append({"date": as_of.isoformat(), "league": lg, "team": team,
                                 "venue": venue, "kind": kind,
                                 "value": f"{val:.4f}", "n": n})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return {"date": as_of.isoformat(), "rows": len(rows), "teams": len({r["team"] for r in rows})}


def load(path: str = PATH) -> Tuple[Dict[tuple, tuple], Optional[date]]:
    """Return {(league, team, venue, kind): (value, n)}, generated_date."""
    if not os.path.exists(path):
        return {}, None
    out, gen = {}, None
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                d = date.fromisoformat(r["date"])
                val = float(r["value"])
                n = int(r["n"])
            except (KeyError, ValueError):
                continue
            gen = max(gen, d) if gen else d
            out[(r["league"], r["team"], r["venue"], r["kind"])] = (val, n)
    return out, gen
