# Football Odds History → Excel

This tool fetches a chosen team's match history **and pre-match odds** and exports them to an Excel file.

## Data source
- **API-FOOTBALL (API-Sports)** v3: https://www.api-football.com/
  - Fixtures: `https://v3.football.api-sports.io/fixtures`
  - Odds (prematch): `https://v3.football.api-sports.io/odds`

> Free keys are available; sign up at https://dashboard.api-football.com/ (API-SPORTS).  

## Output
Excel with:
- Sheet **`data`**: one row per match  
  Columns: `DateUTC, League, Season, Round, Home, Away, FixtureID, Status, HomeGoals, AwayGoals, Outcome(H/D/A), Odds_H, Odds_D, Odds_A, TeamSide, TeamOdds`
- Sheet **`summary`**: basic period summary.

## Quick start

1) **Install Python 3.10+**  
2) In a terminal:
```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3) **API key**  
Create a `.env` file in the project folder (or edit the existing template) and set:
```
API_FOOTBALL_KEY=YOUR_API_SPORTS_KEY
```

4) **Run**
```bash
python main.py --team "Arsenal" --from 2024-08-01 --to 2025-06-30
```
Optional:
- `--league "Premier League"` : filter by league name
- `--season 2024`             : restrict to specific season
- `--out my_report.xlsx`      : custom output filename

If no key is present, the script will **fall back to a built-in sample** dataset, so you can see the Excel structure.

## Notes
- Odds used: **prematch 1x2 (Match Winner)**. For each fixture we pick the **latest bookmaker snapshot *before* kickoff**.
- API rate limits: the script retries automatically with exponential backoff.
- Extend easily to more markets (BTTS, Handicap, Over/Under) by adding parsing in `pick_prematch_1x2`.

## Troubleshooting
- *No rows in Excel*: make sure your dates cover real fixtures for the team; try removing `--league` or specifying a correct `--season`.
- *401/403*: your API key is missing or invalid; check `.env`.
