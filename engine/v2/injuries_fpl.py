"""
engine/v2/injuries_fpl.py

Free injury/doubt data for the Premier League from the public FPL API.

This is the one league where a free, current availability feed exists. The
other four leagues stay neutral until a feed is chosen. The output is merged
into data/injuries.csv; engine/v2/injuries.py turns it into a small expected-
goals multiplier.

Run:  python -m engine.v2.injuries_fpl
"""

import csv
import os
from datetime import date, datetime, timezone
from typing import List

PATH = "data/injuries.csv"
FIELDS = ["date", "league", "team", "player", "status", "importance"]

# FPL display name -> football-data.co.uk canonical name
TEAM_MAP = {
    "Man Utd": "Man United", "Spurs": "Tottenham", "Coventry City": "Coventry",
    "Hull City": "Hull", "Ipswich Town": "Ipswich",
}


def importance(starts: int, xgi90: float) -> float:
    """0..1: how much of the team's threat this player represents."""
    s = min(1.0, (starts or 0) / 20.0)
    x = min(1.0, (xgi90 or 0.0) / 0.8)
    return round(min(1.0, 0.65 * s + 0.35 * x), 2)


def fetch_rows(today: date = None) -> List[dict]:
    import requests
    today = today or datetime.now(timezone.utc).date()
    r = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/",
                     timeout=30, headers={"User-Agent": "OraclePitch/2.0"})
    r.raise_for_status()
    data = r.json()
    teams = {t["id"]: TEAM_MAP.get(t["name"], t["name"]) for t in data.get("teams", [])}
    out = []
    for e in data.get("elements", []):
        status = e.get("status")
        chance = e.get("chance_of_playing_next_round")
        if status == "a" or e.get("removed"):
            continue
        if chance is not None and chance >= 100:
            continue
        imp = importance(e.get("starts") or 0, e.get("expected_goal_involvements_per_90") or 0)
        if imp <= 0:
            continue
        out.append({
            "date": today.isoformat(), "league": "epl", "team": teams.get(e.get("team"), ""),
            "player": e.get("web_name") or e.get("second_name") or "",
            "status": "doubtful" if status == "d" else "out",
            "importance": f"{imp:.2f}",
        })
    return [x for x in out if x["team"]]


def update(path: str = PATH, today: date = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f)
                    if not (r.get("league") == "epl" and r.get("date") == today.isoformat())]
    new = fetch_rows(today)
    rows.extend(new)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["date"], r["league"], r["team"], r["player"])):
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return len(new)


def main():
    n = update()
    print(f"wrote {n} FPL availability rows")


if __name__ == "__main__":
    main()
