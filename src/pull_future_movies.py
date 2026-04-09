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
]


def fetch_page(api_key: str, year: int, page: int, *, sort_by: str, min_vote_count: int = None) -> dict:
    params = {
        "api_key": api_key,
        "include_adult": "false",
        "include_video": "false",
        "language": "en-US",
        "page": page,
        "primary_release_year": year,
        "sort_by": sort_by,
        "with_original_language": "en",
    }
    if min_vote_count is not None:
        params["vote_count.gte"] = min_vote_count
    url = f"{TMDB_BASE_URL}?{urlencode(params)}"
    with _urlopen_with_retry(url) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_results(results: list[dict], year: int) -> pd.DataFrame:
    rows = []
    for item in results:
        release_date = item.get("release_date") or None
        rows.append(
            {
                "title": item.get("title"),
                "release_date": release_date,
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
            }
        )

    df = pd.DataFrame(rows, columns=FUTURE_MOVIE_COLUMNS)
    if df.empty:
        return df

    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    df = df.sort_values(["release_date", "no_of_persons_voted"], ascending=[True, False])
    df = df.drop_duplicates(subset=["title", "release_date"], keep="first")
    return df


def fetch_all_results(api_key: str, year: int, *, sort_by: str, min_vote_count: int = None) -> list[dict]:
    first_page = fetch_page(api_key, year, page=1, sort_by=sort_by, min_vote_count=min_vote_count)
    all_results = list(first_page.get("results", []))
    total_pages = min(first_page.get("total_pages", 1), 500)  # TMDb caps at 500 pages
    for page in range(2, total_pages + 1):
        time.sleep(_PAGE_DELAY)
        payload = fetch_page(api_key, year, page=page, sort_by=sort_by, min_vote_count=min_vote_count)
        all_results.extend(payload.get("results", []))
    return all_results


def pull_tmdb_movies(year: int) -> pd.DataFrame:
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        raise EnvironmentError("TMDB_API_KEY is not set.")

    attempts = [
        {
            "label": "vote-screened release-date query",
            "sort_by": "primary_release_date.asc",
            "min_vote_count": 5,
        }
    ]
    if year >= date.today().year + 1:
        attempts.extend(
            [
                {
                    "label": "release-date fallback without vote filter",
                    "sort_by": "primary_release_date.asc",
                    "min_vote_count": None,
                },
                {
                    "label": "popularity fallback without vote filter",
                    "sort_by": "popularity.desc",
                    "min_vote_count": None,
                },
            ]
        )

    for attempt in attempts:
        all_results = fetch_all_results(
            api_key,
            year,
            sort_by=attempt["sort_by"],
            min_vote_count=attempt["min_vote_count"],
        )
        if all_results:
            if attempt["label"] != attempts[0]["label"]:
                print(f"TMDb fallback used for {year}: {attempt['label']}.")
            return normalize_results(all_results, year)

    print(f"TMDb returned no discover results for {year} across all query variants.")
    return normalize_results([], year)


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
