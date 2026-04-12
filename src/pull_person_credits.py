"""
Pull person credits (lead actor, lead actress, director) from TMDb for all films
in the award-season pool for a given year.

Output: data/raw/tmdb_credits_{year}.csv
Columns: tmdb_id, title, lead_actor_id, lead_actor_name, lead_actor_profile_url,
         lead_actress_id, lead_actress_name, lead_actress_profile_url,
         director_id, director_name, director_profile_url
"""

import argparse
import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w185"
RATE_LIMIT_DELAY = 0.25  # seconds between requests
MAX_RETRIES = 3
TOP_CAST_N = 5  # Only look at top N billed cast members


def _get_api_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        raise EnvironmentError("TMDB_API_KEY environment variable is not set.")
    return key


def _profile_url(profile_path) -> str:
    if not profile_path or str(profile_path) == "nan":
        return ""
    return f"{TMDB_IMAGE_BASE}{profile_path}"


def fetch_credits(tmdb_id: int, api_key: str) -> dict:
    """
    Fetch credits for a TMDb movie ID with retry logic.
    Returns the raw JSON response dict or empty dict on failure.
    """
    url = f"{TMDB_BASE}/movie/{tmdb_id}/credits"
    params = {"api_key": api_key}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                # Rate limited — back off exponentially
                wait = (2 ** attempt) * 1.0
                print(f"  [tmdb] Rate limited on {tmdb_id}, waiting {wait}s...")
                time.sleep(wait)
            elif resp.status_code == 404:
                print(f"  [tmdb] 404 for tmdb_id={tmdb_id}")
                return {}
            else:
                print(f"  [tmdb] HTTP {resp.status_code} for tmdb_id={tmdb_id} (attempt {attempt+1})")
                time.sleep(2 ** attempt)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"  [tmdb] Request error for tmdb_id={tmdb_id}: {exc} (attempt {attempt+1}, retry in {wait}s)")
            time.sleep(wait)

    return {}


def extract_credits(credits_json: dict) -> dict:
    """
    Extract lead actor (male), lead actress (female), and director from credits JSON.

    Lead actor  = first cast member in top-5 billed where known_for_department == "Acting" AND gender == 2
    Lead actress = first cast member in top-5 billed where known_for_department == "Acting" AND gender == 1
    Director    = first crew member where job == "Director"
    """
    cast = credits_json.get("cast", [])
    crew = credits_json.get("crew", [])

    lead_actor = {}
    lead_actress = {}
    director = {}

    top_cast = cast[:TOP_CAST_N]

    for member in top_cast:
        dept = member.get("known_for_department", "")
        gender = member.get("gender", 0)
        if dept == "Acting":
            if gender == 2 and not lead_actor:
                lead_actor = member
            elif gender == 1 and not lead_actress:
                lead_actress = member
        if lead_actor and lead_actress:
            break

    for member in crew:
        if member.get("job") == "Director":
            director = member
            break

    return {
        "lead_actor_id": lead_actor.get("id", ""),
        "lead_actor_name": lead_actor.get("name", ""),
        "lead_actor_profile_url": _profile_url(lead_actor.get("profile_path")),
        "lead_actress_id": lead_actress.get("id", ""),
        "lead_actress_name": lead_actress.get("name", ""),
        "lead_actress_profile_url": _profile_url(lead_actress.get("profile_path")),
        "director_id": director.get("id", ""),
        "director_name": director.get("name", ""),
        "director_profile_url": _profile_url(director.get("profile_path")),
    }


def pull_credits_for_year(year: int):
    """
    Pull TMDb credits for all films in the award-season pool for the given year.
    Reads data/raw/tmdb_movies_{year}.csv and writes data/raw/tmdb_credits_{year}.csv.
    """
    api_key = _get_api_key()

    movies_path = RAW_DIR / f"tmdb_movies_{year}.csv"
    if not movies_path.exists():
        print(f"[tmdb_credits] No movie pool file at {movies_path}. Nothing to do.")
        return

    movies_df = pd.read_csv(movies_path)
    if "tmdb_id" not in movies_df.columns or "title" not in movies_df.columns:
        raise ValueError(f"Expected columns 'tmdb_id' and 'title' in {movies_path}")

    print(f"[tmdb_credits] Pulling credits for {len(movies_df)} films (year={year})...")

    records = []
    for i, row in movies_df.iterrows():
        tmdb_id = int(row["tmdb_id"])
        title = str(row["title"])
        print(f"  [{i+1}/{len(movies_df)}] {title} (id={tmdb_id})")

        credits_json = fetch_credits(tmdb_id, api_key)
        extracted = extract_credits(credits_json)

        record = {"tmdb_id": tmdb_id, "title": title}
        record.update(extracted)
        records.append(record)

        time.sleep(RATE_LIMIT_DELAY)

    out_df = pd.DataFrame(records)
    out_path = RAW_DIR / f"tmdb_credits_{year}.csv"
    out_df.to_csv(out_path, index=False)
    print(f"[tmdb_credits] Wrote {len(out_df)} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pull TMDb cast/crew credits for award-season films.")
    parser.add_argument("--year", type=int, default=date.today().year,
                        help="Award season year (i.e. year_film). Default: current year.")
    args = parser.parse_args()
    pull_credits_for_year(args.year)
