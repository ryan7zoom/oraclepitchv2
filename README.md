# OraclePitch v2

A daily football prediction dashboard for the top five European leagues.

Each match gets:

1. a model probability for 1X2, double chance, both teams to score, match totals and team totals;
2. a correlated same-game builder built from those markets plus selected corners/shots/cards form legs;
3. historical form notes for corners, shots, shots on target and cards (shown as `9/10`, never presented as model probabilities);
4. the full model market list, with standalone Asian handicaps at the very bottom.

No Champions League. No handicaps inside the builder.

## Daily pipeline

The schedule is split deliberately:

- **Daily (04:00 UTC):** results, closing odds, Premier League injuries, fixtures, predictions, builder, page.
- **Weekly (Monday 05:00 UTC):** fresh ClubElo and xG rating snapshots.
- **Manual daily run:** can force the ratings refresh with the `refresh_ratings` input, or run the weekly workflow manually.

```
data/matches/*.csv
  + weekly ClubElo snapshot
  + weekly xG snapshot
        |
        v
team rates (time-decayed, opponent-adjusted, shrunk)
        |
        v
Dixon-Coles goals model  ->  1X2 / DC / totals / team totals / BTTS
        |
        +--> correlated simulation -> corners / shots / SOT / cards / most corners / most cards
        |
        v
same-game builder (greedy, constraint-aware, joint probability from the simulation)
        |
        v
docs/index.html + data/v2/latest.json
```

Commands:

```bash
python -m engine.data.update           # results, xG and odds
python -m engine.v2.injuries_fpl       # Premier League availability (FPL)
python -m engine.v2.refresh            # force a weekly ClubElo + xG refresh
python -m engine.v2.run --days 3       # fixtures, model, builder, page
python -m engine.v2.run --fixtures fixtures.json --date 2026-11-28
python -m engine.v2.backtest --from-season 2025
python tests/test_v2.py
```

`docs/index.html` is the deployed page. `data/v2/latest.json` is the machine-readable version. `data/v2/ledger.csv` freezes every fixture before kickoff and grades the 1X2 / O2.5 / BTTS calls as results arrive; the page header shows the live record once it has graded matches.

## Model

Per fixture, in `engine/v2/goals.py`:

```
expected goals = 0.60 * xG form + 0.40 * goals form
supremacy      = 0.35 * Elo prior + 0.65 * team-strength supremacy
lambda_home    = (total + supremacy) / 2
lambda_away    = (total - supremacy) / 2
score grid     = bivariate Poisson + Dixon-Coles low-score correction
```

- Team rates are time-decayed (150-day half-life), venue-specific and shrunk toward the league average, so three games cannot swing a rating.
- `engine/v2/power.py` uses ClubElo when a recent snapshot exists, otherwise a local Elo table replayed from the match history. ClubElo is cached at `data/power/clubelo.csv`.
- `xG` is used only where football-data.co.uk supplies it. At the time of writing that is the current season; earlier seasons fall back to goals. The daily model reads the weekly team-xG snapshot in `data/power/xg.csv`; `engine/v2/refresh.py` rebuilds it every Monday (or on manual dispatch).
- Injuries are an optional multiplier (`engine/v2/injuries.py`, `data/injuries.csv`). The Premier League is populated from the free FPL API (`engine/v2/injuries_fpl.py`); the other four leagues stay neutral until a source is chosen. Missing feed data never invents an injury effect.

## Builder

`engine/v2/builder.py` selects 3–5 legs from:

- model: result, double chance, BTTS, match totals, team totals
- form: team/match corners, shots, shots on target (over only), cards, most corners, most cards

Constraints:

- one leg per group;
- no contradictory legs;
- each leg has a reasonable individual chance (55–90% for model legs);
- form legs need at least 8 games and a 70% historical hit rate;
- the joint probability is always measured on the correlated simulation, never by multiplying the legs.

The page shows a best slip and a safer 3-leg version. The builder is probability-first: without a real price on every leg it cannot be an EV optimiser.

## Data sources and constraints

- **football-data.co.uk**: results, shots, SOT, corners, cards, xG and odds. Free for private use only; their terms explicitly exclude commercial and AI/data-training products. Pinnacle prices have been unreliable since July 2025, so closing market averages are preferable.
- **ClubElo** (`clubelo.com`): free daily European club Elo. The ranking page used here exposes the top 100; clubs outside it fall back to the local Elo. Global Football Rankings (GFR) is not wired in: its pages are client-rendered and it has no documented public API. GFR can be added later as a manual weekly snapshot or a benchmark.
- **ESPN**: fixtures, results and some match stats. Unofficial API.
- **FPL**: free current availability for the Premier League only.
- **Odds** are stored separately in `data/odds/*.csv` as a benchmark, not fed into the model.

Not included: tackles, throw-ins, free kicks (no free source in the existing data); UCL; player-level expected lineups; a complete injury feed.

## Current backtest

Walk-forward, 2,300 matches from 2025-26 and 2026-27 (`python -m engine.v2.backtest --from-season 2025`):

| | 1X2 log loss | league base rate | closing market |
|---|---:|---:|---:|
| all five leagues | 1.007 | 1.072 | 0.971 |

Over/under 2.5 log loss is 0.683 versus 0.669 for the closing market; BTTS is 0.690 and home-team over 1.5 is 0.660. The model beats the league base rate but is not yet at the closing line. That is the honest starting point, not a claim of an edge.

The total is shrunk 40% toward the league average (`TOTAL_SHRINK = 0.60`), fitted on the 2025-27 walk-forward. That improved both 1X2 and O/U log loss and removed most of the overconfidence in the 0.6-0.8 total buckets. The calibration snapshot is written to `data/v2/backtest.json`.
