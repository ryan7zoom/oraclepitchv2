"""
engine/v2/backtest.py

Walk-forward check for the v2 goals model.

  python -m engine.v2.backtest --from-season 2025

For every match from the chosen season onward:
  * predict it using only earlier matches
  * score 1X2 with log loss and Brier
  * score over/under 2.5
  * compare with the league base rate and, where available, closing odds

The point is not a pretty number. It is to see whether xG + Elo is better
than the base rate, and how far it still is from the closing line.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Dict

from engine.data import odds as odds_store
from engine.v2.features import LEAGUES, TeamBook
from engine.v2.goals import GoalModel
from engine.v2.power import Power

SEASON_FROM = 2025


def logloss(p: float, hit: int) -> float:
    return -math.log(max(1e-9, min(1 - 1e-9, p))) if hit else -math.log(max(1e-9, 1 - p))


def brier(p: float, hit: int) -> float:
    return (p - hit) ** 2


def run(data_dir: str, from_season: int = SEASON_FROM):
    book = TeamBook.from_dir(data_dir)
    odds = {lg: odds_store.load(lg) for lg in LEAGUES}
    rows = []
    for lg in LEAGUES:
        dates = sorted({m.date for m in book.raw[lg] if m.season >= from_season and m.finished})
        power_by_date: Dict[date, Power] = {}
        model_by_date: Dict[date, GoalModel] = {}
        for d in dates:
            p = Power(book, d, use_clubelo=False)
            power_by_date[d] = p
            model_by_date[d] = GoalModel(book, p, d)
        for m in book.raw[lg]:
            if m.season < from_season or not m.finished:
                continue
            pred = model_by_date[m.date].predict(lg, m.home, m.away)
            r = pred.result()
            out = "H" if m.ft_h > m.ft_a else "D" if m.ft_h == m.ft_a else "A"
            base = book.league_means(lg, m.date)["goals"]
            # league base rates from the same window
            hist = [x for x in book.raw[lg] if x.finished and x.date < m.date][-500:]
            if not hist:
                continue
            bh = sum(1 for x in hist if x.ft_h > x.ft_a) / len(hist)
            bd = sum(1 for x in hist if x.ft_h == x.ft_a) / len(hist)
            ba = 1 - bh - bd
            basep = {"H": bh, "D": bd, "A": ba}
            base_lam = (book.league_means(lg, m.date)["goals"].home,
                        book.league_means(lg, m.date)["goals"].away)
            over_prob = pred.total_over(2.5)
            actual_over = (m.ft_h + m.ft_a) > 2.5
            btts_prob = pred.btts()["Y"]
            actual_btts = m.ft_h > 0 and m.ft_a > 0
            team_prob = pred.team_over("home", 1.5)
            actual_team = m.ft_h > 1.5
            o = odds[lg].get((m.date.isoformat(), m.home, m.away))
            mkt = odds_store.closing_probs(o) if o else None
            rows.append({
                "league": lg, "date": m.date, "home": m.home, "away": m.away,
                "model": r, "base": basep, "base_lam": base_lam, "pred": pred,
                "out": out, "over_prob": over_prob, "actual_over": actual_over,
                "btts_prob": btts_prob, "actual_btts": actual_btts,
                "team_prob": team_prob, "actual_team": actual_team,
                "mkt": mkt,
            })
    return rows


def summarize(rows):
    out = {}
    by = defaultdict(list)
    for r in rows:
        by[r["league"]].append(r)
        by["ALL"].append(r)
    for name, rs in by.items():
        n = len(rs)
        if not n:
            continue
        ll_model = sum(logloss(r["model"][r["out"]], 1) for r in rs) / n
        ll_base = sum(logloss(r["base"][r["out"]], 1) for r in rs) / n
        br_model = sum(brier(r["model"][r["out"]], 1) for r in rs) / n
        br_base = sum(brier(r["base"][r["out"]], 1) for r in rs) / n
        ou_model = sum(-math.log(max(1e-9, r["over_prob"] if r["actual_over"]
                                    else 1 - r["over_prob"])) for r in rs) / n
        btts_model = sum(-math.log(max(1e-9, r["btts_prob"] if r["actual_btts"]
                                     else 1 - r["btts_prob"])) for r in rs) / n
        team_model = sum(-math.log(max(1e-9, r["team_prob"] if r["actual_team"]
                                     else 1 - r["team_prob"])) for r in rs) / n
        mkt = [r for r in rs if r["mkt"]]
        ll_mkt = sum(logloss(r["mkt"][r["out"]], 1) for r in mkt) / len(mkt) if mkt else None
        out[name] = {"n": n, "logloss": ll_model, "base": ll_base, "brier": br_model,
                     "brier_base": br_base, "over_logloss": ou_model,
                     "btts_logloss": btts_model, "team15_logloss": team_model,
                     "market": ll_mkt, "market_n": len(mkt)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/matches")
    ap.add_argument("--from-season", type=int, default=SEASON_FROM)
    ap.add_argument("--out", default="data/v2/backtest.json")
    a = ap.parse_args()
    rows = run(a.data_dir, a.from_season)
    res = summarize(rows)
    print(f"{'league':12}{'n':>6}{'logloss':>10}{'base':>9}{'OU':>8}{'market':>9}{'mkt n':>7}")
    for lg, r in sorted(res.items()):
        print(f"{lg:12}{r['n']:6d}{r['logloss']:10.4f}{r['base']:9.4f}"
              f"{r['over_logloss']:8.4f}{(r['market'] if r['market'] is not None else 0):9.4f}{r['market_n']:7d}")
    if a.out:
        import os
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                       "from_season": a.from_season, "summary": res}, f, indent=1)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
