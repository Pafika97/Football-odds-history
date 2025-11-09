#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch match history and pre-match odds for a chosen football team and export to Excel.

Data source: API-FOOTBALL (API-Sports) v3 https://www.api-football.com/
- Fixtures endpoint: https://v3.football.api-sports.io/fixtures
- Odds endpoint:     https://v3.football.api-sports.io/odds

Usage examples:
  python main.py --team "Arsenal" --from 2024-08-01 --to 2025-06-30
  python main.py --team "Real Madrid" --from 2025-01-01 --to 2025-11-01 --market "1x2"

If no API key is configured, the script will fall back to sample data so you can see the output format.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv

API_BASE = "https://v3.football.api-sports.io"
DEFAULT_MARKET = "1x2"  # match-winner market
OUTPUT_XLSX = "odds_history.xlsx"

def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

class APIError(Exception):
    pass

def parse_args():
    p = argparse.ArgumentParser(description="Export team match history with pre-match odds to Excel")
    p.add_argument("--team", required=True, help="Team name in plain text, e.g., 'Arsenal', 'FC Barcelona'")
    p.add_argument("--from", dest="date_from", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="End date YYYY-MM-DD (inclusive)")
    p.add_argument("--market", default=DEFAULT_MARKET, help="Odds market, default '1x2' (match winner)")
    p.add_argument("--league", default=None, help="Optional league name filter (e.g., 'Premier League')")
    p.add_argument("--season", default=None, help="Optional season (e.g., 2024)")
    p.add_argument("--out", default=OUTPUT_XLSX, help="Output Excel filename")
    return p.parse_args()

def get_headers():
    # API-FOOTBALL (API-Sports) uses header x-apisports-key
    key = os.getenv("API_FOOTBALL_KEY") or os.getenv("APISPORTS_KEY")
    if not key:
        return None
    return {
        "x-apisports-key": key
    }

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
       retry=retry_if_exception_type(APIError))
def api_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    headers = get_headers()
    if headers is None:
        raise APIError("NO_API_KEY")
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 429:
        # Rate limited – backoff
        raise APIError("RATE_LIMIT")
    if r.status_code >= 300:
        raise APIError(f"HTTP_{r.status_code}: {r.text[:200]}")
    data = r.json()
    return data

def find_team_id(team_name: str) -> Optional[int]:
    # Search teams by name (may return multiple – we pick the best exact/partial match)
    data = api_get("/teams", {"search": team_name})
    results = data.get("response", [])
    if not results:
        return None
    # Prefer exact case-insensitive match
    for item in results:
        name = item.get("team", {}).get("name")
        if name and name.lower() == team_name.lower():
            return item.get("team", {}).get("id")
    # Fallback to first result
    return results[0].get("team", {}).get("id")

def list_fixtures(team_id: int, date_from: str, date_to: str, league_name: Optional[str], season: Optional[str]) -> List[Dict[str, Any]]:
    params = {
        "team": team_id,
        "from": date_from,
        "to": date_to,
        "status": "FT,NS,1H,2H,ET,P"  # completed or scheduled
    }
    if season:
        params["season"] = season
    data = api_get("/fixtures", params)
    fixtures = data.get("response", [])
    # Optional filter by league name if provided
    if league_name:
        fixtures = [f for f in fixtures if league_name.lower() in (f.get("league", {}).get("name", "").lower())]
    # sort by date ascending
    fixtures.sort(key=lambda x: x.get("fixture", {}).get("date", ""))
    return fixtures

def extract_score(ft: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    goals = ft.get("goals", {})
    return goals.get("home"), goals.get("away")

def safe_get(d: Dict[str, Any], path: List[str], default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur

def outcome_from_score(home_goals: Optional[int], away_goals: Optional[int]) -> Optional[str]:
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"

def pick_prematch_1x2(odds_resp: Dict[str, Any], kickoff_iso: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Choose the closest bookmaker snapshot BEFORE kickoff for market 1x2 (Home/Draw/Away).
    """
    resp = odds_resp.get("response", [])
    if not resp:
        return (None, None, None)

    kickoff = datetime.fromisoformat(kickoff_iso.replace("Z","+00:00"))
    best_dt = None
    best_triple = (None, None, None)

    for fixture in resp:
        for book in fixture.get("bookmakers", []):
            for bet in book.get("bets", []):
                if bet.get("name", "").lower() in ("match winner", "1x2"):
                    for val in bet.get("values", []):
                        # val example: {"value": "Home", "odd": "1.85"}
                        pass
                    # Bookmaker may have an update time
                    updated = book.get("update", None)
                    try:
                        updated_dt = datetime.fromisoformat(updated.replace("Z","+00:00")) if updated else None
                    except Exception:
                        updated_dt = None
                    # We need the last snapshot not after kickoff
                    if updated_dt and updated_dt <= kickoff:
                        # Extract odds H/D/A
                        H = D = A = None
                        for val in bet.get("values", []):
                            name = (val.get("value") or "").strip().lower()
                            try:
                                odd = float(val.get("odd"))
                            except Exception:
                                odd = None
                            if name in ("home", "1"):
                                H = odd
                            elif name in ("draw", "x"):
                                D = odd
                            elif name in ("away", "2"):
                                A = odd
                        if H or D or A:
                            if (best_dt is None) or (updated_dt > best_dt):
                                best_dt = updated_dt
                                best_triple = (H, D, A)
    return best_triple

def get_fixture_odds_1x2(fixture_id: int, kickoff_iso: str, market: str = "1x2") -> Tuple[Optional[float], Optional[float], Optional[float]]:
    params = {"fixture": fixture_id, "type": "prematch"}
    data = api_get("/odds", params)
    return pick_prematch_1x2(data, kickoff_iso)

def build_dataframe(fixtures: List[Dict[str, Any]], team_name: str, fetch_odds: bool) -> pd.DataFrame:
    rows = []
    for f in fixtures:
        fixture = f.get("fixture", {})
        league = f.get("league", {})
        teams = f.get("teams", {})
        date_iso = fixture.get("date")
        fixture_id = fixture.get("id")
        home = safe_get(f, ["teams", "home", "name"])
        away = safe_get(f, ["teams", "away", "name"])
        home_goals, away_goals = extract_score(f)
        outcome = outcome_from_score(home_goals, away_goals)

        H = D = A = None
        if fetch_odds:
            try:
                H, D, A = get_fixture_odds_1x2(fixture_id, date_iso)
                time.sleep(0.25)  # be nice to the API
            except APIError as e:
                if str(e) == "NO_API_KEY":
                    fetch_odds = False  # fallback
                else:
                    log(f"Warning: odds for fixture {fixture_id} not fetched: {e}")

        # Compute team's implied odds column (odds for the chosen team)
        team_side = None
        team_odds = None
        if home and home.lower() == team_name.lower():
            team_side = "Home"
            team_odds = H
        elif away and away.lower() == team_name.lower():
            team_side = "Away"
            team_odds = A

        rows.append({
            "DateUTC": date_iso,
            "League": league.get("name"),
            "Season": league.get("season"),
            "Round": league.get("round"),
            "Home": home,
            "Away": away,
            "Kickoff_Timestamp": fixture.get("timestamp"),
            "FixtureID": fixture_id,
            "Status": safe_get(f, ["fixture", "status", "short"]),
            "HomeGoals": home_goals,
            "AwayGoals": away_goals,
            "Outcome": outcome,  # H/D/A
            "Odds_H": H,
            "Odds_D": D,
            "Odds_A": A,
            "TeamSide": team_side,
            "TeamOdds": team_odds,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["DateUTC"] = pd.to_datetime(df["DateUTC"])
        df.sort_values("DateUTC", inplace=True)
    return df

def export_excel(df: pd.DataFrame, out_path: str, team_name: str, date_from: str, date_to: str):
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="data", index=False)
        # Summary sheet
        summary = {}
        summary["Team"] = team_name
        summary["Period"] = f"{date_from} → {date_to}"
        summary["Matches"] = int(len(df))
        if "Outcome" in df.columns and not df["Outcome"].isna().all():
            summary["Wins(H/A)"] = int(((df["Outcome"]=="H") & (df["TeamSide"]=="Home")).sum() + ((df["Outcome"]=="A") & (df["TeamSide"]=="Away")).sum())
            summary["Draws"] = int((df["Outcome"]=="D").sum())
            summary["Losses(H/A)"] = int(((df["Outcome"]=="A") & (df["TeamSide"]=="Home")).sum() + ((df["Outcome"]=="H") & (df["TeamSide"]=="Away")).sum())
        summary_df = pd.DataFrame([summary])
        summary_df.to_excel(writer, sheet_name="summary", index=False)

def main():
    args = parse_args()
    load_dotenv()
    team = args.team.strip()
    date_from = args.date_from
    date_to = args.date_to
    market = args.market
    league_name = args.league
    season = args.season
    out = args.out

    headers = get_headers()
    use_api = headers is not None
    try:
        if use_api:
            log(f"Finding team id for '{team}' ...")
            team_id = find_team_id(team)
            if team_id is None:
                log("Team not found via API search. Exiting.")
                sys.exit(2)
            log(f"Team ID: {team_id}")
            log("Fetching fixtures ...")
            fixtures = list_fixtures(team_id, date_from, date_to, league_name, season)
            log(f"Found fixtures: {len(fixtures)}")
            log("Fetching odds (prematch 1x2) ...")
            df = build_dataframe(fixtures, team, fetch_odds=True)
        else:
            log("No API key found – using sample data (set API_FOOTBALL_KEY in .env for live data).")
            sample_path = os.path.join(os.path.dirname(__file__), "sample_data.csv")
            if not os.path.exists(sample_path):
                log(f"Sample file not found at {sample_path}")
                sys.exit(3)
            df = pd.read_csv(sample_path, parse_dates=["DateUTC"])
            df = df[(df["Home"].str.contains(team, case=False)) | (df["Away"].str.contains(team, case=False))]
            df = df[(df["DateUTC"]>=pd.to_datetime(date_from)) & (df["DateUTC"]<=pd.to_datetime(date_to))]
            df.sort_values("DateUTC", inplace=True)

        export_excel(df, out, team, date_from, date_to)
        log(f"Saved Excel to {out}")
    except APIError as e:
        if str(e) == "NO_API_KEY":
            log("No API key configured. Please set API_FOOTBALL_KEY in .env")
        else:
            log(f"API error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
