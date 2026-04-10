import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd


ALGOLIA_APP_ID = "79FRDP12PN"
ALGOLIA_SEARCH_KEY = "175588f6e5f8319b27702e4cc4013561"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_HEADERS = {
    "X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "Content-Type": "application/json",
    "User-Agent": "OscarPredictorBot/1.0 (Rotten Tomatoes refresh)",
}
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
CACHE_COLUMNS = [
    "year_film",
    "film",
    "film_key",
    "release_month",
    "query",
    "status",
    "matched_title",
    "matched_vanity",
    "matched_release_year",
    "tomatometer_rating",
    "audience_rating",
    "poster_url",
    "rt_url",
    "match_score",
    "match_reason",
    "rt_updated_at",
    "fetched_at",
    "error_message",
]


def _urlopen_with_retry(request: Request, timeout: int = REQUEST_TIMEOUT, max_retries: int = MAX_RETRIES):
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        try:
            return urlopen(request, timeout=timeout)
        except (URLError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last_exc


def normalize_title(value) -> str:
    if value is None or pd.isna(value):
        return ""

    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_film_key(value) -> str:
    return normalize_title(value)


def title_variants(value) -> set[str]:
    base = normalize_title(value)
    if not base:
        return set()

    variants = {base}
    for article in ("the ", "a ", "an "):
        if base.startswith(article):
            variants.add(base[len(article):])
    variants.add(base.replace(" and ", " "))
    return {variant.strip() for variant in variants if variant.strip()}


def _safe_int(value) -> Optional[int]:
    try:
        if value is None or pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _iter_hit_titles(hit: dict) -> list[str]:
    titles = [hit.get("title")]
    titles.extend(hit.get("titles") or [])
    titles.extend(hit.get("aka") or [])
    return [title for title in titles if title]


def _match_details(film: str, year_film: int, hit: dict) -> dict:
    candidate_variants = title_variants(film)
    hit_variants = set()
    for title in _iter_hit_titles(hit):
        hit_variants.update(title_variants(title))

    exact_match = bool(candidate_variants & hit_variants)
    overlap_candidates = [candidate for candidate in candidate_variants if len(candidate.split()) >= 2]
    overlap_match = any(
        candidate in hit_title or hit_title in candidate
        for candidate in overlap_candidates
        for hit_title in hit_variants
    )

    ratios = [
        SequenceMatcher(None, candidate, hit_title).ratio()
        for candidate in candidate_variants
        for hit_title in hit_variants
        if candidate and hit_title
    ]
    best_ratio = max(ratios) if ratios else 0.0

    release_year = _safe_int(hit.get("releaseYear"))
    year_delta = abs(release_year - int(year_film)) if release_year is not None else 99
    critics_score = _safe_int((hit.get("rottenTomatoes") or {}).get("criticsScore"))

    score = int(best_ratio * 40)
    reasons = [f"ratio={best_ratio:.2f}"]

    if exact_match:
        score += 120
        reasons.append("exact-title")
    elif overlap_match:
        score += 20
        reasons.append("overlap-title")

    if year_delta == 0:
        score += 30
        reasons.append("exact-year")
    elif year_delta == 1:
        score += 18
        reasons.append("year-plus-one")
    elif year_delta == 2:
        score += 6
        reasons.append("year-close")
    else:
        score -= min(year_delta * 8, 40)
        reasons.append(f"year-delta={year_delta}")

    if hit.get("type") == "movie":
        score += 5
    if hit.get("titleType") == "main":
        score += 4
        reasons.append("main-title")
    if critics_score is not None:
        score += 6
        reasons.append("has-score")

    return {
        "match_score": score,
        "match_reason": ", ".join(reasons),
        "exact_match": exact_match,
        "overlap_match": overlap_match,
        "matched_release_year": release_year,
    }


def choose_best_movie_hit(film: str, year_film: int, hits: list[dict]) -> tuple[Optional[dict], dict]:
    ranked = []
    for hit in hits:
        details = _match_details(film, year_film, hit)
        ranked.append((hit, details))

    ranked.sort(key=lambda item: item[1]["match_score"], reverse=True)
    if not ranked:
        return None, {"match_score": 0, "match_reason": "no-search-results"}

    best_hit, best_details = ranked[0]
    runner_details = ranked[1][1] if len(ranked) > 1 else None

    if best_details["match_score"] < 90:
        return None, {
            "match_score": best_details["match_score"],
            "match_reason": f"low-confidence: {best_details['match_reason']}",
        }

    if (
        runner_details is not None
        and runner_details["match_score"] >= best_details["match_score"] - 4
        and not best_details["exact_match"]
    ):
        return None, {
            "match_score": best_details["match_score"],
            "match_reason": (
                f"ambiguous-match: best={best_details['match_reason']} "
                f"runner={runner_details['match_reason']}"
            ),
        }

    return best_hit, best_details


def search_movie_hits_batch(queries: list[str], hits_per_page: int = 10) -> list[list[dict]]:
    if not queries:
        return []

    payload = {
        "requests": [
            {
                "indexName": "content_rt",
                "params": (
                    f"query={quote(query)}&filters=isEmsSearchable%20%3D%201&hitsPerPage={hits_per_page}"
                ),
            }
            for query in queries
        ]
    }
    request = Request(
        ALGOLIA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=ALGOLIA_HEADERS,
        method="POST",
    )
    with _urlopen_with_retry(request) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [result.get("hits", []) for result in data.get("results", [])]


def _normalize_cache_df(cache_df: pd.DataFrame) -> pd.DataFrame:
    if cache_df.empty:
        return pd.DataFrame(columns=CACHE_COLUMNS)

    df = cache_df.copy()
    for column in CACHE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = df["film_key"].fillna(df["film"].map(clean_film_key))
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], errors="coerce", utc=True)
    return df[CACHE_COLUMNS]


def refresh_rt_match_cache(
    candidates: pd.DataFrame,
    cache_path: Path,
    *,
    stale_days: int = 30,
    batch_size: int = 20,
    request_pause: float = 0.25,
) -> pd.DataFrame:
    candidate_df = candidates.copy()
    if candidate_df.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        empty = pd.DataFrame(columns=CACHE_COLUMNS)
        empty.to_csv(cache_path, index=False)
        return empty

    candidate_df["year_film"] = pd.to_numeric(candidate_df["year_film"], errors="coerce")
    candidate_df["film"] = candidate_df["film"].astype(str).str.strip()
    candidate_df["film_key"] = candidate_df["film"].map(clean_film_key)
    candidate_df["release_month"] = pd.to_numeric(candidate_df.get("release_month"), errors="coerce")
    candidate_df["release_month_priority"] = candidate_df["release_month"].notna().astype(int)
    candidate_df = candidate_df.sort_values(
        ["year_film", "film_key", "release_month_priority"],
        ascending=[True, True, False],
    )
    candidate_df = candidate_df.drop_duplicates(subset=["year_film", "film_key"], keep="first")

    existing = pd.DataFrame(columns=CACHE_COLUMNS)
    if cache_path.exists():
        existing = _normalize_cache_df(pd.read_csv(cache_path))
        existing = existing.sort_values("fetched_at").drop_duplicates(
            subset=["year_film", "film_key"], keep="last"
        )

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    reusable_rows = []
    refresh_targets = []

    existing_map = {
        (int(row["year_film"]), row["film_key"]): row
        for _, row in existing.dropna(subset=["year_film", "film_key"]).iterrows()
    }

    for _, row in candidate_df.iterrows():
        key = (int(row["year_film"]), row["film_key"])
        cached = existing_map.get(key)
        if (
            cached is not None
            and pd.notna(cached["fetched_at"])
            and cached["fetched_at"].to_pydatetime() >= stale_cutoff
            and str(cached.get("status", "")) in {"matched", "unmatched", "manual"}
        ):
            cached_row = cached.to_dict()
            cached_row["film"] = row["film"]
            cached_row["release_month"] = (
                int(row["release_month"]) if pd.notna(row["release_month"]) else cached_row.get("release_month")
            )
            reusable_rows.append(cached_row)
        else:
            refresh_targets.append(row.to_dict())

    refreshed_rows = []
    timestamp = datetime.now(timezone.utc).isoformat()

    for start in range(0, len(refresh_targets), batch_size):
        chunk = refresh_targets[start:start + batch_size]
        queries = [item["film"] for item in chunk]
        try:
            batch_hits = search_movie_hits_batch(queries, hits_per_page=10)
        except Exception as exc:
            for candidate in chunk:
                refreshed_rows.append(
                    {
                        "year_film": int(candidate["year_film"]),
                        "film": candidate["film"],
                        "film_key": candidate["film_key"],
                        "release_month": candidate.get("release_month"),
                        "query": candidate["film"],
                        "status": "error",
                        "matched_title": pd.NA,
                        "matched_vanity": pd.NA,
                        "matched_release_year": pd.NA,
                        "tomatometer_rating": pd.NA,
                        "audience_rating": pd.NA,
                        "poster_url": pd.NA,
                        "rt_url": pd.NA,
                        "match_score": pd.NA,
                        "match_reason": pd.NA,
                        "rt_updated_at": pd.NA,
                        "fetched_at": timestamp,
                        "error_message": str(exc),
                    }
                )
            continue

        for candidate, hits in zip(chunk, batch_hits):
            best_hit, details = choose_best_movie_hit(candidate["film"], int(candidate["year_film"]), hits)
            if best_hit is None:
                refreshed_rows.append(
                    {
                        "year_film": int(candidate["year_film"]),
                        "film": candidate["film"],
                        "film_key": candidate["film_key"],
                        "release_month": candidate.get("release_month"),
                        "query": candidate["film"],
                        "status": "unmatched",
                        "matched_title": pd.NA,
                        "matched_vanity": pd.NA,
                        "matched_release_year": pd.NA,
                        "tomatometer_rating": pd.NA,
                        "audience_rating": pd.NA,
                        "poster_url": pd.NA,
                        "rt_url": pd.NA,
                        "match_score": details["match_score"],
                        "match_reason": details["match_reason"],
                        "rt_updated_at": pd.NA,
                        "fetched_at": timestamp,
                        "error_message": pd.NA,
                    }
                )
                continue

            rt = best_hit.get("rottenTomatoes") or {}
            vanity = best_hit.get("vanity")
            refreshed_rows.append(
                {
                    "year_film": int(candidate["year_film"]),
                    "film": candidate["film"],
                    "film_key": candidate["film_key"],
                    "release_month": candidate.get("release_month"),
                    "query": candidate["film"],
                    "status": "matched",
                    "matched_title": best_hit.get("title"),
                    "matched_vanity": vanity,
                    "matched_release_year": _safe_int(best_hit.get("releaseYear")),
                    "tomatometer_rating": _safe_int(rt.get("criticsScore")),
                    "audience_rating": _safe_int(rt.get("audienceScore")),
                    "poster_url": best_hit.get("posterImageUrl"),
                    "rt_url": f"https://www.rottentomatoes.com/m/{vanity}" if vanity else pd.NA,
                    "match_score": details["match_score"],
                    "match_reason": details["match_reason"],
                    "rt_updated_at": best_hit.get("updateDate"),
                    "fetched_at": timestamp,
                    "error_message": pd.NA,
                }
            )

        if request_pause > 0 and start + batch_size < len(refresh_targets):
            time.sleep(request_pause)

    cache_df = pd.DataFrame(reusable_rows + refreshed_rows, columns=CACHE_COLUMNS)
    cache_df["year_film"] = pd.to_numeric(cache_df["year_film"], errors="coerce")
    cache_df = cache_df.sort_values(["year_film", "film"], na_position="last")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_df.to_csv(cache_path, index=False)
    return cache_df
