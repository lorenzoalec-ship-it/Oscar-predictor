import argparse
from datetime import date
import json
import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

_REQUEST_TIMEOUT = 15
_MAX_RETRIES = 3
_PAGE_DELAY = 0.25


def _urlopen_with_retry(url: str, timeout: int = _REQUEST_TIMEOUT, max_retries: int = _MAX_RETRIES):
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        try:
            return urlopen(url, timeout=timeout)
        except (URLError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last_exc


TMDB_BASE_URL = "https://api.themoviedb.org/3/discover/movie"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
DEFAULT_OUTPUT_DIR = Path("data/raw")
FUTURE_MOVIE_COLUMNS = [
    "title",
    "release_date",
    "year",
    "tmdb_id",
    "overview",
    "original_language",
    "genre_ids",
    "poster_path",
    "poster_url",
    "backdrop_path",
    "backdrop_url",
    "rating",
    "no_of_persons_voted",
    "popularity",
    "adult",
    "pre_release",
]


def fetch_page(
    api_key: str,
    year: int,
    page: int,
    *,
    sort_by: str,
    min_vote_count: int = None,
    date_gte: str = None,
    date_lte: str = None,
) -> dict:
    params = {
        "api_key": api_key,
        "include_adult": "false",
        "include_video": "false",
        "language": "en-US",
        "page": page,
        "sort_by": sort_by,
        "with_original_language": "en",
    }
    if date_gte or date_lte:
        # Date-range mode — don't use primary_release_year so we can target future dates
        if date_gte:
            params["primary_release_date.gte"] = date_gte
        if date_lte:
            params["primary_release_date.lte"] = date_lte
    else:
        params["primary_release_year"] = year
    if min_vote_count is not None:
        params["vote_count.gte"] = min_vote_count
    url = f"{TMDB_BASE_URL}?{urlencode(params)}"
    with _urlopen_with_retry(url) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_results(results: list[dict], year: int, pre_release: bool = False) -> pd.DataFrame:
    today = date.today()
    rows = []
    for item in results:
        release_date_str = item.get("release_date") or None
        # Determine pre_release flag: no release date yet, or release date is in the future
        if pre_release:
            is_pre = 1
        elif release_date_str:
            try:
                rd = date.fromisoformat(release_date_str)
                is_pre = 1 if rd > today else 0
            except ValueError:
                is_pre = 0
        else:
            is_pre = 1  # No release date = not yet out

        rows.append(
            {
                "title": item.get("title"),
                "release_date": release_date_str,
                "year": year,
                "tmdb_id": item.get("id"),
                "overview": item.get("overview"),
                "original_language": item.get("original_language"),
                "genre_ids": ",".join(str(genre_id) for genre_id in item.get("genre_ids", [])),
                "poster_path": item.get("poster_path"),
                "poster_url": (
                    f"{TMDB_IMAGE_BASE_URL}{item.get('poster_path')}"
                    if item.get("poster_path")
                    else pd.NA
                ),
                "backdrop_path": item.get("backdrop_path"),
                "backdrop_url": (
                    f"{TMDB_IMAGE_BASE_URL}{item.get('backdrop_path')}"
                    if item.get("backdrop_path")
                    else pd.NA
                ),
                "rating": item.get("vote_average"),
                "no_of_persons_voted": item.get("vote_count"),
                "popularity": item.get("popularity"),
                "adult": item.get("adult"),
                "pre_release": is_pre,
            }
        )

    df = pd.DataFrame(rows, columns=FUTURE_MOVIE_COLUMNS)
    if df.empty:
        return df

    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    df = df.sort_values(["release_date", "no_of_persons_voted"], ascending=[True, False])
    df = df.drop_duplicates(subset=["title", "release_date"], keep="first")

    # Filter out TV Movies (TMDb genre 10770) — they are not Oscar-eligible
    before = len(df)
    df = df[~df["genre_ids"].str.contains("10770", na=False)]
    removed = before - len(df)
    if removed:
        print(f"Filtered {removed} TV Movie entries (genre 10770).")

    return df


def fetch_all_results(
    api_key: str,
    year: int,
    *,
    sort_by: str,
    min_vote_count: int = None,
    date_gte: str = None,
    date_lte: str = None,
) -> list[dict]:
    first_page = fetch_page(
        api_key, year, page=1, sort_by=sort_by,
        min_vote_count=min_vote_count, date_gte=date_gte, date_lte=date_lte,
    )
    all_results = list(first_page.get("results", []))
    total_pages = min(first_page.get("total_pages", 1), 500)  # TMDb caps at 500 pages
    for page in range(2, total_pages + 1):
        time.sleep(_PAGE_DELAY)
        payload = fetch_page(
            api_key, year, page=page, sort_by=sort_by,
            min_vote_count=min_vote_count, date_gte=date_gte, date_lte=date_lte,
        )
        all_results.extend(payload.get("results", []))
    return all_results


def pull_tmdb_movies(year: int) -> pd.DataFrame:
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        raise EnvironmentError("TMDB_API_KEY is not set.")

    today = date.today()

    # --- Pass 1: Already-released films (vote_count >= 5 ensures real screenings) ---
    released_results = fetch_all_results(
        api_key, year,
        sort_by="primary_release_date.asc",
        min_vote_count=5,
    )
    released_df = normalize_results(released_results, year)
    print(f"Pass 1 (released, vote≥5): {len(released_df)} films")

    # --- Pass 2: Upcoming films releasing later this year (no vote filter) ---
    # Captures announced titles not yet in wide release — festival premiere candidates.
    # Only run for the current or next eligibility year; historical years are complete.
    upcoming_df = pd.DataFrame(columns=FUTURE_MOVIE_COLUMNS)
    if year >= today.year:
        date_gte = max(today.isoformat(), f"{year}-01-01")
        date_lte = f"{year}-12-31"
        upcoming_results = fetch_all_results(
            api_key, year,
            sort_by="popularity.desc",
            min_vote_count=None,
            date_gte=date_gte,
            date_lte=date_lte,
        )
        upcoming_df = normalize_results(upcoming_results, year, pre_release=True)
        print(f"Pass 2 (upcoming, no vote filter): {len(upcoming_df)} films")

    # --- Merge: keep released records; add upcoming films not already captured ---
    if released_df.empty and upcoming_df.empty:
        print(f"TMDb returned no results for {year}.")
        return normalize_results([], year)

    if released_df.empty:
        return upcoming_df
    if upcoming_df.empty:
        return released_df

    released_keys = set(released_df["title"].str.strip().str.lower().dropna())
    new_upcoming = upcoming_df[
        ~upcoming_df["title"].str.strip().str.lower().isin(released_keys)
    ].copy()
    print(f"Adding {len(new_upcoming)} net-new upcoming films to pool")

    combined = pd.concat([released_df, new_upcoming], ignore_index=True)
    combined = combined.sort_values(
        ["pre_release", "release_date", "no_of_persons_voted"],
        ascending=[True, True, False],
    )
    return combined


def output_path_for_year(year: int) -> Path:
    return DEFAULT_OUTPUT_DIR / f"tmdb_movies_{year}.csv"


def run(year: int):
    movies = pull_tmdb_movies(year)
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = output_path_for_year(year)
    movies.to_csv(output_path, index=False)

    print(f"Pulled {len(movies)} movies for {year}.")
    print(f"Saved to {output_path}")
    if not movies.empty:
        print(movies[["title", "release_date", "rating", "no_of_persons_voted"]].head(20).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pull TMDb releases for a future Oscars eligibility year.")
    parser.add_argument("--year", type=int, required=True, help="Eligibility year, for example 2026.")
    args = parser.parse_args()
    run(args.year)
