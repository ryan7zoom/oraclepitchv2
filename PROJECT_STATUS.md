# OraclePitch — project location and status

**Project root (this is the folder to open, commit and push):**

```
C:\Users\Ryan\Documents\deepseek-harness\default-workspace\oraclepitch-main\oraclepitch-main
```

The folder one level above (`...\oraclepitch-main`) is only the ZIP-extraction wrapper. Do **not** push the wrapper: it would create a nested `oraclepitch-main/oraclepitch-main` repository.

## Current build

- Dashboard: `docs/index.html`
- Predictions JSON: `data/v2/latest.json`
- Backtest evidence: `data/v2/backtest.json`
- Pre-kickoff ledger: `data/v2/ledger.csv`
- Model/builder: `engine/v2/`
- Daily workflow: `.github/workflows/daily_dashboard.yml`

## Run

```powershell
cd "C:\Users\Ryan\Documents\deepseek-harness\default-workspace\oraclepitch-main\oraclepitch-main"
python -m engine.data.update
python -m engine.v2.injuries_fpl
python -m engine.v2.run --days 3
```

Ratings cadence:

- ClubElo and xG: weekly, `python -m engine.v2.refresh` (Monday workflow or manual).
- Results, odds, injuries, fixtures and the page: daily.
- Manual daily dispatch can force the ratings refresh with `refresh_ratings = true`.

## Git

As of 2026-11-27 this folder has **no `.git` directory**. It is not connected to GitHub yet.

Create an empty GitHub repository (no README, no .gitignore, no licence), then:

```powershell
cd "C:\Users\Ryan\Documents\deepseek-harness\default-workspace\oraclepitch-main\oraclepitch-main"
git init
git add -A
git commit -m "OraclePitch v2"
git branch -M main
git remote add origin https://github.com/YOUR-USER/YOUR-REPO.git
git push -u origin main
```

GitHub Pages: Settings → Pages → Deploy from a branch → `main` / `/docs`.

## Important before making the repository public

The committed `data/matches/*.csv` and `data/odds/*.csv` are derived from football-data.co.uk, whose terms are for private individual use and exclude commercial/AI data products. For that reason a **private repository** is the safe default. If you want a public repository, keep the raw data out of it (or move the raw data to a private repository) and publish only the generated `docs/` page.

`git add -A` will not include `.tmptest/`, `.chrome/`, `.edge/` or `__pycache__/`; these are in `.gitignore`.
