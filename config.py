"""
config.py

Shared paths and limits for the data layer and the legacy model.

The live product is now OraclePitch v2 in engine/v2/: a Dixon-Coles goals
model driven by xG, power ratings (ClubElo/local Elo), recent form and an
optional injury layer, plus a correlated same-game builder. The old
engine/model code is kept for reference and its tests; it is no longer the
page that the daily workflow builds.
"""

# ---------------------------------------------------------------------------
# League
# ---------------------------------------------------------------------------
LEAGUE_NAME = "English Premier League"

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
PREDICTIONS_JSON_PATH = "data/predictions/latest.json"
HTML_OUTPUT_PATH = "docs/index.html"
HISTORICAL_DATA_DIR = "data/historical"

# ---------------------------------------------------------------------------
# Streak analysis (double-streak mismatch dashboard)
# ---------------------------------------------------------------------------
# See engine/streaks/analyzer.py's module docstring for the full design
# rationale on "for"/"against"/H2H streaks and mismatch detection.
#
# NOTE: "goals_conceded" is kept here even though it wasn't listed in
# the pivot spec's example config - it was already implemented and
# tested (engine/streaks/analyzer.py's get_stat_value()/
# get_opponent_stat_value() both handle it), and removing a working,
# tested stat category for no functional reason would just be
# needless deletion. If it turns out to be unwanted noise in the
# dashboard, it's a one-line removal from this dict, not a design
# problem.
STREAK_THRESHOLDS = {
    "shots_on_target": [3, 4, 5, 6],
    "corners": [5, 6, 7, 8, 9],
    "goals": [1, 2, 3],
    "goals_conceded": [1, 2, 3],
}

# Window sizes for single-team recent-form streaks. A mix of short
# (noisy but recent) and long (stable but slower to react) windows,
# since different streak lengths surface different patterns.
STREAK_WINDOWS = [5, 6, 7, 8, 10, 13, 18]

# Window sizes for head-to-head streaks specifically (separate from
# STREAK_WINDOWS since H2H meetings between two specific teams are far
# less frequent than each team's overall match list).
H2H_WINDOWS = [5, 10, 15]

# A double-streak mismatch requires BOTH the "for" streak and the
# "against" streak to independently clear this percentage before being
# considered at all.
MISMATCH_MIN_PERCENTAGE = 0.60

# Minimum number of matches with usable data a streak must have before
# it's considered reliable enough to contribute to a mismatch.
MISMATCH_MIN_WINDOW = 5

# ---------------------------------------------------------------------------
# Match data layer (engine/data/) - football-data.co.uk + ESPN
# ---------------------------------------------------------------------------
# One CSV per league lives here and is committed by the update workflow, so
# the ESPN-only stats (offsides) accumulate over time instead of being
# re-fetched.
MATCH_DATA_DIR = "data/matches"

# Seasons of football-data.co.uk history kept per league (current + N back).
DATA_SEASONS_BACK = 5

# ESPN is the only free source of offsides. It needs one request per match,
# so it is only used for the most recent seasons (current + N-1 back).
OFFSIDES_SEASONS = 2

# Max ESPN HTTP requests per run (scoreboard + summary). The daily run needs
# a few dozen; the first backfill is spread over several runs.
ESPN_REQUEST_BUDGET = 600

# A match ESPN could not supply data for is retried this many times, then
# left alone (avoids wasting the budget on matches ESPN does not have).
ESPN_MAX_TRIES = 2

# Days back from today always re-checked on ESPN (catches matches that
# football-data.co.uk has not posted yet).
ESPN_RECENT_DAYS = 10

# Offsides/cards are not modelled any more, so by default ESPN is only used to
# add matches football-data.co.uk has not posted yet (a few requests a day).
# Set True to resume the offsides backfill.
ESPN_FILL_OFFSIDES = False


# ---------------------------------------------------------------------------
# Leagues with no football-data.co.uk file. ESPN is their only match source,
# so team names are taken as ESPN spells them and history is backfilled from
# ESPN's daily scoreboards over several runs (skipping the Jun-Jul off-season).
# ---------------------------------------------------------------------------
ESPN_ONLY_LEAGUES = {"saudi"}

# How far back the first backfill reaches (days). About two seasons.
ESPN_BACKFILL_DAYS = 600

# Optional xG from FotMob for those leagues (unofficial endpoint, best effort).
# If FotMob refuses the request the run carries on without xG.
FOTMOB_XG_LEAGUES = {"saudi": "KSA"}      # league key -> FotMob country code
FOTMOB_MAX_REQUESTS = 60                  # per run (day lists + match pages)
FOTMOB_MAX_TRIES = 2                      # per match, then left alone
