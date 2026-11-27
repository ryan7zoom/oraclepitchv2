"""
engine/v2/injuries.py

A deliberately small, optional injury layer.

There is no free, complete injury feed for all five leagues. This module reads
a manually maintained / later-scraped CSV and turns unavailable players into a
small multiplier on a team's expected goals. It is neutral (1.00) when the file
is missing, so the model never invents an injury effect.

CSV columns: date,league,team,player,status,importance
  status      out | doubtful
  importance  0..1 (1 = key player)
"""

import csv
import os
from collections import defaultdict
from datetime import date
from typing import Dict, Optional

PATH = "data/injuries.csv"
OUT_FACTOR = 0.06          # each "importance unit" out removes 6% of a team's threat
DOUBT_FACTOR = 0.03
FLOOR = 0.80


class InjuryBook:
    def __init__(self, rows=None):
        self.rows = rows or []

    @classmethod
    def load(cls, path: str = PATH) -> "InjuryBook":
        if not os.path.exists(path):
            return cls([])
        with open(path, newline="", encoding="utf-8") as f:
            return cls(list(csv.DictReader(f)))

    def factor(self, league: str, team: str, as_of: date) -> float:
        loss = 0.0
        for r in self.rows:
            if r.get("league") != league or r.get("team") != team:
                continue
            try:
                d = date.fromisoformat(r.get("date", ""))
                imp = float(r.get("importance", 0) or 0)
            except (ValueError, TypeError):
                continue
            if d > as_of:
                continue
            status = (r.get("status") or "").lower()
            if status == "out":
                loss += OUT_FACTOR * max(0.0, min(1.0, imp))
            elif status == "doubtful":
                loss += DOUBT_FACTOR * max(0.0, min(1.0, imp))
        return max(FLOOR, 1.0 - loss)
