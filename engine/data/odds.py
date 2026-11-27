"""
engine/data/odds.py

Free closing/pre-closing odds from football-data.co.uk.

The match CSVs already carry these columns, but the match table deliberately
keeps only football stats. Odds live in their own file so they can be used as
a benchmark (and later for CLV) without polluting the model inputs.

Files: data/odds/<league>.csv
Key:   (league, date, home, away)

Only the columns we actually use are kept:
  PSH/PSD/PSA        Pinnacle pre-closing (note: unreliable since Jul 2025)
  PSC*               Pinnacle closing
  Avg*/AvgC*         market average pre-closing / closing
  Max*/MaxC*         market maximum pre-closing / closing
  B365*/B365C*       Bet365 pre-closing / closing
  o25/u25, o25c/u25c over/under 2.5 pre-closing / closing
"""

import csv
import io
import logging
import os
from datetime import datetime
from typing import Dict, Optional

from engine.data import http
from engine.data.football_data import DIVISIONS, URL, parse_date, season_code

logger = logging.getLogger("engine.data.odds")

OUT_DIR = "data/odds"

# output column -> source column candidates (first present wins)
COLMAP = {
    "psh": ("PSH",), "psd": ("PSD",), "psa": ("PSA",),
    "psch": ("PSC H", "PSCH", "PSCH"), "pscd": ("PSC D", "PSCD"), "psca": ("PSC A", "PSCA"),
    "avgh": ("AvgH",), "avgd": ("AvgD",), "avga": ("AvgA",),
    "avgch": ("AvgCH",), "avgcd": ("AvgCD",), "avgca": ("AvgCA",),
    "maxh": ("MaxH",), "maxd": ("MaxD",), "maxa": ("MaxA",),
    "maxch": ("MaxCH",), "maxcd": ("MaxCD",), "maxca": ("MaxCA",),
    "b365h": ("B365H",), "b365d": ("B365D",), "b365a": ("B365A",),
    "b365ch": ("B365CH",), "b365cd": ("B365CD",), "b365ca": ("B365CA",),
    "o25": ("B365>2.5", "Avg>2.5"), "u25": ("B365<2.5", "Avg<2.5"),
    "o25c": ("B365C>2.5", "AvgC>2.5"), "u25c": ("B365C<2.5", "AvgC<2.5"),
}
FIELDS = ["league", "season", "date", "home", "away"] + list(COLMAP)


def _float(v) -> Optional[float]:
    try:
        v = (v or "").strip()
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def _pick(row: dict, names) -> Optional[float]:
    for n in names:
        if n in row:
            v = _float(row[n])
            if v is not None:
                return v
    return None


def parse_rows(text: str, league: str, season: int) -> list:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        d = parse_date(row.get("Date", ""))
        home = (row.get("HomeTeam") or "").strip()
        away = (row.get("AwayTeam") or "").strip()
        if not (d and home and away):
            continue
        rec = {"league": league, "season": season, "date": d.isoformat(),
               "home": home, "away": away}
        for name, candidates in COLMAP.items():
            rec[name] = _pick(row, candidates)
        if any(rec[k] is not None for k in ("avgh", "avgch", "b365h", "psh")):
            out.append(rec)
    return out


def fetch_season(league: str, season: int, session) -> list:
    url = URL.format(code=season_code(season), div=DIVISIONS[league])
    r = http.get(session, url)
    if r.status_code != 200:
        return []
    return parse_rows(r.content.decode("utf-8-sig", errors="replace"), league, season)


def _path(league: str) -> str:
    return os.path.join(OUT_DIR, f"{league}.csv")


def load(league: str) -> Dict[tuple, dict]:
    path = _path(league)
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        rec = dict(r)
        for k in COLMAP:
            rec[k] = _float(r.get(k))
        out[(r["date"], r["home"], r["away"])] = rec
    return out


def save(league: str, rows: Dict[tuple, dict]) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_path(league), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for key in sorted(rows, key=lambda k: (k[0], k[1], k[2])):
            w.writerow(rows[key])


def update(league: str, seasons, session) -> int:
    rows = load(league)
    added = 0
    for season in seasons:
        for rec in fetch_season(league, season, session):
            key = (rec["date"], rec["home"], rec["away"])
            if key not in rows:
                added += 1
            rows[key] = rec
    save(league, rows)
    logger.info(f"[{league}] odds rows={len(rows)} (+{added})")
    return added


def closing_probs(row: dict) -> Optional[dict]:
    """Market-implied closing probabilities (overround removed) for 1X2."""
    if not row:
        return None
    h, d, a = row.get("avgch"), row.get("avgcd"), row.get("avgca")
    if not all(isinstance(x, (int, float)) and x > 1 for x in (h, d, a)):
        h, d, a = row.get("psch"), row.get("pscd"), row.get("psca")
    if not all(isinstance(x, (int, float)) and x > 1 for x in (h, d, a)):
        return None
    inv = [1 / h, 1 / d, 1 / a]
    s = sum(inv)
    return {"H": inv[0] / s, "D": inv[1] / s, "A": inv[2] / s}
