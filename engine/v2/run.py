"""
engine/v2/run.py

The daily v2 job:   python -m engine.v2.run

  data/matches/*.csv -> team rates + Elo/xG -> goals model
  ESPN (or --fixtures) -> today's top-five fixtures
  each fixture -> probabilities + same-game builder + form notes
  -> data/v2/latest.json + docs/index.html
"""

import argparse
import json
import logging
import os
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

from engine.trends.names import display
from engine.v2 import MODEL_VERSION, builder, form, goals, ledger, markets, ratings, render, shapes, sim
from engine.v2.features import LEAGUES, TeamBook
from engine.v2.fixtures import Fixture, fetch as fetch_fixtures, from_json, league_name
from engine.v2.injuries import InjuryBook
from engine.v2.power import Power

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("engine.v2.run")

GMT8 = timezone(timedelta(hours=8))
DEFAULT_JSON = "data/v2/latest.json"
DEFAULT_HTML = "docs/index.html"


def _pick_text(pred: goals.GoalPrediction) -> str:
    r = pred.result()
    best = max(r, key=r.get)
    home, away = display(pred.home), display(pred.away)
    outcome = {"H": f"{home} win", "D": "Draw", "A": f"{away} win"}[best]
    mt = markets.main_total(pred)
    b = pred.btts()["Y"]
    btts = "BTTS yes" if b >= 0.5 else "BTTS no"
    return f"{outcome} {r[best]*100:.0f}% · {mt.label} {mt.prob*100:.0f}% · {btts} {(b if b >= 0.5 else 1-b)*100:.0f}%"


def _form(points: list) -> str:
    return "".join({3: "W", 1: "D", 0: "L"}.get(p, "?") for p in points) or "—"


def _backtest() -> dict:
    try:
        with open("data/v2/backtest.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _most(sm, home: str, away: str) -> list:
    out = []
    for ch, ca, label in (("c_h", "c_a", "most corners"), ("yc_h", "yc_a", "most cards")):
        a, b = sm.column(ch), sm.column(ca)
        out.append({"label": f"{display(home)} {label}", "prob": float((a > b).mean())})
        out.append({"label": f"{display(away)} {label}", "prob": float((b > a).mean())})
    return out


def _has_team_stats(book: TeamBook, league: str, as_of) -> bool:
    """Enough shots-on-target and corner data to trust underdog shots/corners picks."""
    ms = [m for m in book.raw.get(league, []) if m.finished and (as_of - m.date).days <= 365]
    if len(ms) < 30:
        return False
    ok = sum(1 for m in ms if m.sot_h is not None and m.sot_a is not None
             and m.co_h is not None and m.co_a is not None)
    return ok / len(ms) >= 0.5


def _card(fx: Fixture, book: TeamBook, power: Power, model: goals.GoalModel,
          corr, n_sim: int) -> dict:
    pred = model.predict(fx.league, fx.home, fx.away)
    stats = book.expected(fx.league, fx.home, fx.away, fx.date)
    sm = sim.simulate(pred, stats, corr, n=n_sim, seed=zlib.crc32(fx.key.encode()) % (2**32))
    ms = markets.build(pred)
    form_cands = form.candidates(book, fx.league, fx.home, fx.away, fx.date, sm)
    team_form, match_form = form.grouped(book, fx.league, fx.home, fx.away, fx.date, sm)
    notes = team_form + match_form
    slips = builder.build(pred, ms, form_cands, sm, max_legs=5)
    safe_shapes = shapes.build(pred, sm, display(fx.home), display(fx.away),
                               include_underdog=_has_team_stats(book, fx.league, fx.date))
    r = pred.result()
    return {
        "league": fx.league,
        "league_name": league_name(fx.league),
        "date": fx.date.isoformat(),
        "date_label": fx.date.strftime("%a %d %b"),
        "kickoff": fx.kickoff.astimezone(GMT8).strftime("%H:%M") if fx.kickoff else "TBC",
        "home": fx.home, "away": fx.away,
        "home_name": fx.home_name or fx.home, "away_name": fx.away_name or fx.away,
        "pred": pred,
        "stats": stats,
        "markets": ms,
        "main_total": markets.main_total(pred),
        "builder": slips,
        "shapes": safe_shapes,
        "notes": notes,
        "team_form": team_form,
        "match_form": match_form,
        "most": _most(sm, fx.home, fx.away),
        "form": {"home": _form(book.points(fx.league, fx.home, fx.date)),
                 "away": _form(book.points(fx.league, fx.away, fx.date))},
        "pick": _pick_text(pred),
        "probabilities": {"H": round(r["H"], 4), "D": round(r["D"], 4), "A": round(r["A"], 4)},
    }


def _as_dict(card: dict) -> dict:
    p = card["pred"]
    return {
        "league": card["league"], "date": card["date"], "kickoff": card["kickoff"],
        "home": card["home"], "away": card["away"],
        "home_name": card["home_name"], "away_name": card["away_name"],
        "probabilities": card["probabilities"],
        "expected_goals": [round(p.lam_h, 3), round(p.lam_a, 3)],
        "pick": card["pick"],
        "elo_source": p.elo_source, "xg_used": p.xg_used,
        "main_total": {"label": card["main_total"].label, "prob": round(card["main_total"].prob, 4)},
        "builder": {"best": card["builder"]["best"].to_dict(),
                    "safe": card["builder"]["safe"].to_dict()},
        "form_notes": [{"label": n.label, "hit": n.hit_text, "prob": round(n.prob, 4),
                        "stat": n.stat, "direction": n.direction, "line": n.line,
                        "subject": n.subject} for n in card["notes"]],
        "team_form": [{"label": n.label, "hit": n.hit_text, "prob": round(n.prob, 4),
                       "stat": n.stat, "direction": n.direction, "line": n.line,
                       "subject": n.subject} for n in card["team_form"]],
        "match_form": [{"label": n.label, "hit": n.hit_text, "prob": round(n.prob, 4),
                        "stat": n.stat, "direction": n.direction, "line": n.line}
                       for n in card["match_form"]],
        "most": [{"label": x["label"], "prob": round(x["prob"], 4)} for x in card["most"]],
        "form": card["form"],
        "safe_builder": (card["shapes"]["pick"].to_dict()
                         if card.get("shapes") and card["shapes"].get("pick") else None),
    }


def run(today: date, days: int, fixtures: List[Fixture], data_dir: str,
        json_path: str, html_path: str, use_clubelo: bool = True,
        n_sim: int = 12000, now: datetime = None,
        ledger_path: str = "data/v2/ledger.csv") -> dict:
    now = now or datetime.now(timezone.utc)
    xg_snapshot, xg_date = ratings.load()
    book = TeamBook.from_dir(data_dir, xg_snapshot=xg_snapshot)
    injuries = InjuryBook.load()
    log.info(f"loaded {sum(len(ms) for ms in book.raw.values())} matches; "
             f"xG snapshot {xg_date or 'live'}")

    cards, warnings = [], []
    if xg_date is None:
        warnings.append("xG ratings snapshot missing; run python -m engine.v2.refresh")
    power_cache: Dict[date, Power] = {}
    model_cache: Dict[tuple, goals.GoalModel] = {}
    corr_cache: Dict[tuple, object] = {}
    source = "local Elo"

    for fx in fixtures:
        if fx.home not in book.teams(fx.league) or fx.away not in book.teams(fx.league):
            warnings.append(f"{fx.home} v {fx.away}: missing match history")
            continue
        as_of = fx.date
        if as_of not in power_cache:
            power_cache[as_of] = Power(book, as_of, use_clubelo=use_clubelo, auto_fetch=False)
        power = power_cache[as_of]
        key = (fx.league, as_of)
        if key not in model_cache:
            model_cache[key] = goals.GoalModel(book, power, as_of, injuries=injuries)
        if key not in corr_cache:
            corr_cache[key] = sim.estimate_corr(book, fx.league, as_of)
        source = power.source
        cards.append(_card(fx, book, power, model_cache[key], corr_cache[key], n_sim))

    through = {lg: (book.last_date(lg).isoformat() if book.last_date(lg) else None) for lg in LEAGUES}
    data_through = max((d for d in through.values() if d), default="n/a")
    rows = ledger.read(ledger_path)
    ledger.upsert(rows, cards, now)
    graded = ledger.grade(rows, book.raw)
    ledger.write(ledger_path, rows)
    record = ledger.summary(rows)
    payload = {
        "generated_at": now.isoformat(),
        "model_version": MODEL_VERSION,
        "model_source": source,
        "xg_snapshot_date": xg_date.isoformat() if xg_date else None,
        "data_through": through,
        "fixtures": [_as_dict(c) for c in cards],
        "warnings": warnings,
        "record": record,
    }

    for path in (json_path, html_path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    page = render.render(cards, now.astimezone(GMT8), data_through, source, warnings,
                         record=record, backtest=_backtest())
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    log.info(f"wrote {json_path} and {html_path}: {len(cards)} fixtures; graded {graded}")
    return payload


def main():
    p = argparse.ArgumentParser(description="Build the v2 prediction page")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--fixtures", default=None, help="JSON fixture list (testing)")
    p.add_argument("--data-dir", default="data/matches")
    p.add_argument("--json", default=DEFAULT_JSON)
    p.add_argument("--html", default=DEFAULT_HTML)
    p.add_argument("--no-clubelo", action="store_true")
    p.add_argument("--sims", type=int, default=12000)
    a = p.parse_args()

    today = (date.fromisoformat(a.date) if a.date else datetime.now(timezone.utc).date())
    if a.fixtures:
        fixtures = from_json(a.fixtures)
        warnings = []
    else:
        book = TeamBook.from_dir(a.data_dir)
        fixtures, warnings = fetch_fixtures(book, today, a.days)
    payload = run(today, a.days, fixtures, a.data_dir, a.json, a.html,
                  use_clubelo=not a.no_clubelo, n_sim=a.sims)
    for w in warnings + payload["warnings"]:
        print("WARN", w)
    print(f"{len(payload['fixtures'])} fixtures; model source={payload['model_source']}")


if __name__ == "__main__":
    main()
