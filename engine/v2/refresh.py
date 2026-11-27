"""
engine/v2/refresh.py

The weekly/manual ratings refresh:

  1. force a fresh ClubElo snapshot
  2. rebuild the team xG for/against snapshot from the current match data

Run:  python -m engine.v2.refresh
The daily workflow does NOT run this; .github/workflows/ratings_weekly.yml does,
and manual dispatch can run it at any time.
"""

import argparse

from engine.v2 import ratings
from engine.v2.features import TeamBook
from engine.v2.power import ClubElo


def main():
    ap = argparse.ArgumentParser(description="Refresh Elo and xG rating snapshots")
    ap.add_argument("--data-dir", default="data/matches")
    a = ap.parse_args()

    ce = ClubElo.fetch()
    print(f"ClubElo: {'ok' if ce else 'FAILED - keeping the existing snapshot'}"
          f"{' (' + str(len(ce.ratings)) + ' clubs)' if ce else ''}")

    book = TeamBook.from_dir(a.data_dir)
    info = ratings.build(book)
    print(f"xG snapshot: {info['rows']} rows, {info['teams']} teams, through {info['date']}")


if __name__ == "__main__":
    main()
