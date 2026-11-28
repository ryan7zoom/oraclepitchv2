"""
engine/data/fotmob.py

Optional, best-effort per-match xG from FotMob for leagues that have no
football-data.co.uk file (the Saudi Pro League).

FotMob has no official free API. This client only makes plain, polite requests
to the public JSON endpoints its own website uses. If FotMob answers 401, 403
or 429 the client stops for the run and everything carries on without xG; it
does not try to get around any block. Matches it cannot fill are retried a
couple of times and then left alone.

Parsing is deliberately tolerant: the xG pair is found by its key/title rather
than by a fixed path, and every parser is a pure function unit-tested with
sample payloads.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

import config
from engine.data import http

logger = logging.getLogger("engine.data.fotmob")

BASE = "https://www.fotmob.com/api"


class FotmobBlocked(Exception):
    """FotMob refused the request (401/403/429): stop for this run."""


class FotmobBudgetExhausted(Exception):
    """The per-run FotMob request budget is used up."""


@dataclass
class FotmobMatch:
    id: str
    home_name: str
    away_name: str
    finished: bool


class FotmobClient:
    def __init__(self, budget: int, delay: float = 0.6, session=None):
        self.budget = budget
        self.used = 0
        self.delay = delay
        self.session = session or http.make_session()

    def _get_json(self, url: str) -> Optional[dict]:
        if self.used >= self.budget:
            raise FotmobBudgetExhausted()
        self.used += 1
        time.sleep(self.delay)
        r = http.get(self.session, url)
        if r.status_code in (401, 403, 429):
            raise FotmobBlocked(f"HTTP {r.status_code}")
        if r.status_code != 200:
            logger.warning(f"FotMob HTTP {r.status_code}: {url}")
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def matches_on(self, day, ccode: str) -> List[FotmobMatch]:
        data = self._get_json(f"{BASE}/matches?date={day:%Y%m%d}")
        return parse_day(data, ccode) if data else []

    def xg(self, match_id: str) -> Optional[Tuple[float, float]]:
        data = self._get_json(f"{BASE}/matchDetails?matchId={match_id}")
        return parse_xg(data) if data else None


# ---------------------------------------------------------------------------
# Parsing (pure functions)
# ---------------------------------------------------------------------------
def parse_day(data: dict, ccode: str) -> List[FotmobMatch]:
    """Matches of the top league of one country (e.g. 'KSA') from a day list."""
    out = []
    for lg in (data or {}).get("leagues") or []:
        if str(lg.get("ccode") or "").upper() != ccode.upper():
            continue
        name = str(lg.get("name") or "").lower()
        if "pro league" not in name:
            continue
        for m in lg.get("matches") or []:
            mid = m.get("id")
            home = (m.get("home") or {}).get("name")
            away = (m.get("away") or {}).get("name")
            if mid is None or not home or not away:
                continue
            fin = bool((m.get("status") or {}).get("finished"))
            out.append(FotmobMatch(str(mid), str(home), str(away), fin))
    return out


def _num(v) -> Optional[float]:
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if 0.0 <= x < 12.0 else None


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def parse_xg(data: dict) -> Optional[Tuple[float, float]]:
    """(home xG, away xG) from a match-details payload, or None."""
    for d in _walk(data or {}):
        key = str(d.get("key") or "").lower()
        title = str(d.get("title") or "").lower()
        if key == "expected_goals" or title.startswith("expected goals (xg)") or title == "expected goals":
            st = d.get("stats")
            if isinstance(st, list) and len(st) == 2:
                h, a = _num(st[0]), _num(st[1])
                if h is not None and a is not None:
                    return h, a
    return None


# ---------------------------------------------------------------------------
# Filling the match store
# ---------------------------------------------------------------------------
def _state_path(league: str) -> str:
    return os.path.join(config.MATCH_DATA_DIR, f"_fotmob_{league}.json")


def _load_tries(league: str) -> dict:
    try:
        with open(_state_path(league), encoding="utf-8") as f:
            return dict(json.load(f).get("tries", {}))
    except (OSError, ValueError):
        return {}


def _save_tries(league: str, tries: dict) -> None:
    os.makedirs(config.MATCH_DATA_DIR, exist_ok=True)
    with open(_state_path(league), "w", encoding="utf-8") as f:
        json.dump({"tries": tries}, f, indent=0, sort_keys=True)


def fill_xg(store, league: str, today, client, resolver, report: dict,
            days_back: int = 400) -> None:
    ccode = config.FOTMOB_XG_LEAGUES.get(league)
    if not ccode:
        return
    tries = _load_tries(league)
    floor = today - timedelta(days=days_back)
    need = {}
    for m in store.rows:
        if m.xg_h is None and m.ft_h is not None and m.date >= floor:
            key = f"{m.date.isoformat()}|{m.home}|{m.away}"
            if tries.get(key, 0) < config.FOTMOB_MAX_TRIES:
                need.setdefault(m.date, []).append((key, m))
    filled = 0
    status = "ok"
    try:
        for d in sorted(need, reverse=True):
            found = {}
            for fm in client.matches_on(d, ccode):
                h, a = resolver.lookup(fm.home_name), resolver.lookup(fm.away_name)
                if h and a and fm.finished:
                    found[(h, a)] = fm
            for key, m in need[d]:
                fm = found.get((m.home, m.away))
                xg = client.xg(fm.id) if fm else None
                if xg is None:
                    tries[key] = tries.get(key, 0) + 1
                    continue
                m.xg_h, m.xg_a = xg
                m.add_source("fotmob")
                filled += 1
    except FotmobBlocked as e:
        status = f"blocked ({e}); carrying on without xG"
        logger.warning(f"[{league}] FotMob {status}")
    except FotmobBudgetExhausted:
        status = "budget used up; will continue next run"
        logger.info(f"[{league}] FotMob {status}")
    finally:
        _save_tries(league, tries)
    report["fotmob_xg_filled"] = filled
    report["fotmob_status"] = status
