"""
engine/v2/ledger.py

Every fixture is written down before kickoff, then graded against the result
when the match appears in the data. This is the only honest way to know
whether the daily page is improving.

Columns are deliberately small: the 1X2 probabilities, over/under 2.5, BTTS,
the builder's joint chance and its legs. The page can show a live record
without re-running the old model.
"""

import csv
import os
from datetime import date, datetime
from typing import Dict, List

FIELDS = ["date", "league", "home", "away", "made_on", "p_h", "p_d", "p_a",
          "over25", "btts", "builder_joint", "builder_legs", "graded",
          "result", "hit_result", "hit_over", "hit_btts"]


def read(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path: str, rows: List[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["date"], r["league"], r["home"], r["away"])):
            w.writerow({k: r.get(k, "") for k in FIELDS})


def upsert(rows: List[dict], cards: List[dict], now: datetime) -> None:
    idx = {(r["date"], r["league"], r["home"], r["away"]): r for r in rows}
    for c in cards:
        key = (c["date"], c["league"], c["home"], c["away"])
        if key in idx:
            r = idx[key]
            if r.get("graded") == "1":
                continue
            # refresh an ungraded fixture until kickoff
            r["made_on"] = now.isoformat(timespec="seconds")
        else:
            r = {"date": c["date"], "league": c["league"], "home": c["home"], "away": c["away"],
                 "made_on": now.isoformat(timespec="seconds"), "graded": "0"}
            rows.append(r)
            idx[key] = r
        p = c["pred"]
        r["p_h"] = f"{p.result()['H']:.4f}"
        r["p_d"] = f"{p.result()['D']:.4f}"
        r["p_a"] = f"{p.result()['A']:.4f}"
        r["over25"] = f"{p.total_over(2.5):.4f}"
        r["btts"] = f"{p.btts()['Y']:.4f}"
        best = c["builder"]["best"]
        r["builder_joint"] = f"{best.joint:.4f}"
        r["builder_legs"] = " | ".join(l.label for l in best.legs)


def grade(rows: List[dict], matches_by_league: Dict[str, list]) -> int:
    by_key = {}
    for lg, ms in matches_by_league.items():
        for m in ms:
            if m.finished:
                by_key[(m.date.isoformat(), lg, m.home, m.away)] = m
    n = 0
    for r in rows:
        if r.get("graded") == "1":
            continue
        m = by_key.get((r["date"], r["league"], r["home"], r["away"]))
        if m is None:
            continue
        out = "H" if m.ft_h > m.ft_a else "D" if m.ft_h == m.ft_a else "A"
        r["result"] = out
        r["hit_result"] = "1" if max((float(r["p_h"]), "H"), (float(r["p_d"]), "D"),
                                     (float(r["p_a"]), "A"))[1] == out else "0"
        over = m.ft_h + m.ft_a > 2.5
        r["hit_over"] = "1" if (float(r["over25"]) >= 0.5) == over else "0"
        btts = m.ft_h > 0 and m.ft_a > 0
        r["hit_btts"] = "1" if (float(r["btts"]) >= 0.5) == btts else "0"
        r["graded"] = "1"
        n += 1
    return n


def summary(rows: List[dict]) -> dict:
    g = [r for r in rows if r.get("graded") == "1"]
    if not g:
        return {"n": 0}
    return {
        "n": len(g),
        "result_acc": sum(r["hit_result"] == "1" for r in g) / len(g),
        "over_acc": sum(r["hit_over"] == "1" for r in g) / len(g),
        "btts_acc": sum(r["hit_btts"] == "1" for r in g) / len(g),
        "from": min(r["date"] for r in g),
    }
