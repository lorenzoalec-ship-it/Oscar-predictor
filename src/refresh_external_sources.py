import argparse
import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from rotten_tomatoes_lookup import refresh_rt_match_cache

_REQUEST_TIMEOUT = 15
_MAX_RETRIES = 3


def _urlopen_with_retry(request: Request, timeout: int = _REQUEST_TIMEOUT, max_retries: int = _MAX_RETRIES):
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        try:
            return urlopen(request, timeout=timeout)
        except (URLError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last_exc


AGENT_UPDATES_DIR = Path("data/agent_updates")
RAW_DIR = Path("data/raw")
OSCARS_PATH = Path("data/raw/the_oscar_award.csv")
RT_MANUAL_OVERRIDE_PATH = Path("data/raw/rotten_tomatoes_manual_overrides.csv")
AWARDS_MANIFEST_PATH = AGENT_UPDATES_DIR / "awards_wikipedia_manifest.json"
FILM_MANIFEST_PATH = AGENT_UPDATES_DIR / "film_wikipedia_manifest.csv"
TMDB_POOL_GLOB = "tmdb_movies_*.csv"

GLOBES_OUTPUT_PATH = AGENT_UPDATES_DIR / "golden_globe_recent_summary.csv"
SAG_OUTPUT_PATH = AGENT_UPDATES_DIR / "sag_recent_summary.csv"
BAFTA_OUTPUT_PATH = AGENT_UPDATES_DIR / "bafta_recent_summary.csv"
PGA_OUTPUT_PATH = AGENT_UPDATES_DIR / "pga_recent_summary.csv"
DGA_OUTPUT_PATH = AGENT_UPDATES_DIR / "dga_recent_summary.csv"
CRITICS_CHOICE_OUTPUT_PATH = AGENT_UPDATES_DIR / "critics_choice_recent_summary.csv"
RT_OUTPUT_PATH = AGENT_UPDATES_DIR / "rotten_tomatoes_recent_summary.csv"
RT_CACHE_PATH = AGENT_UPDATES_DIR / "rotten_tomatoes_match_cache.csv"
FESTIVAL_OUTPUT_PATH = AGENT_UPDATES_DIR / "festival_metacritic_summary.csv"
FUTURE_ENRICHMENT_OUTPUT_PATH = AGENT_UPDATES_DIR / "future_contender_enrichment.csv"
RT_REFRESH_START_YEAR = 2000

WIKIPEDIA_API_TEMPLATE = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1"
    "&redirects=1&format=json&titles={title}"
)

REQUEST_HEADERS = {
    "User-Agent": "OscarPredictorBot/1.0 (research refresh; contact local automation)",
    "Accept-Language": "en-US,en;q=0.9",
}

AWARD_OUTPUT_MAP = {
    "golden_globe": GLOBES_OUTPUT_PATH,
    "sag": SAG_OUTPUT_PATH,
    "bafta": BAFTA_OUTPUT_PATH,
    "pga": PGA_OUTPUT_PATH,
    "dga": DGA_OUTPUT_PATH,
    "critics_choice": CRITICS_CHOICE_OUTPUT_PATH,
}

AWARD_COLUMN_MAP = {
    "golden_globe": ("globe_nom_count", "globe_win_count"),
    "sag": ("sag_nom_count", "sag_win_count"),
    "bafta": ("bafta_nom_count", "bafta_win_count"),
    "pga": ("pga_nom_count", "pga_win_count"),
    "dga": ("dga_nom_count", "dga_win_count"),
    "critics_choice": ("critics_choice_nom_count", "critics_choice_win_count"),
}

FESTIVAL_PATTERNS = {
    "cannes_flag": [r"\bCannes Film Festival\b", r"\bFestival de Cannes\b"],
    "venice_flag": [r"\bVenice International Film Festival\b", r"\bVenice Film Festival\b"],
    "tiff_flag": [r"\bToronto International Film Festival\b", r"\bTIFF\b"],
    "telluride_flag": [r"\bTelluride Film Festival\b"],
    "sundance_flag": [r"\bSundance Film Festival\b"],
    "sxsw_flag": [r"\bSXSW\b", r"\bSouth by Southwest\b"],
}


def fetch_json(url: str) -> dict:
    request = Request(url, headers=REQUEST_HEADERS)
    with _urlopen_with_retry(request) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_tables(url: str) -> list[pd.DataFrame]:
    request = Request(url, headers=REQUEST_HEADERS)
    with _urlopen_with_retry(request) as response:
        html = response.read()
    return pd.read_html(html)


def normalize_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\[[^\]]+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_film_key(value) -> str:
    text = normalize_text(value).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_page_extract(wikipedia_title: str) -> str:
    url = WIKIPEDIA_API_TEMPLATE.format(title=quote(wikipedia_title))
    payload = fetch_json(url)
    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        return ""
    page = next(iter(pages.values()))
    return page.get("extract", "") or ""


def parse_metacritic_score(text: str) -> Optional[int]:
    patterns = [
        r"Metacritic[^.]{0,400}?score(?: of)? (\d{1,3}) out of 100",
        r"Metacritic[^.]{0,400}?weighted average score(?: of)? (\d{1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
    return None


def parse_tomatometer_score(text: str) -> Optional[int]:
    patterns = [
        r"Rotten Tomatoes[^.]{0,400}?approval rating of (\d{1,3})%",
        r"On Rotten Tomatoes[^.]{0,400}?approval rating of (\d{1,3})%",
        r"Rotten Tomatoes[^.]{0,400}?(\d{1,3})%",
        r"On Rotten Tomatoes[^.]{0,400}?(\d{1,3})%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
    return None


def parse_release_month(text: str, year_film: int) -> Optional[int]:
    month_names = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    for month_name, month_number in month_names.items():
        if re.search(rf"\b{month_name}\b[^.]*\b{year_film}\b", text, flags=re.IGNORECASE):
            return month_number
    return None


def parse_festival_flags(text: str) -> dict:
    flags = {}
    for column, patterns in FESTIVAL_PATTERNS.items():
        flags[column] = int(any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns))
    return flags


def read_awards_manifest() -> list[dict]:
    if not AWARDS_MANIFEST_PATH.exists():
        return []
    return json.loads(AWARDS_MANIFEST_PATH.read_text())


def read_film_manifest() -> pd.DataFrame:
    if not FILM_MANIFEST_PATH.exists():
        return pd.DataFrame(columns=["year_film", "film", "wikipedia_title", "manual_contender_flag"])
    df = pd.read_csv(FILM_MANIFEST_PATH)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    return df


def read_rt_manual_overrides() -> pd.DataFrame:
    columns = [
        "year_film",
        "film",
        "tomatometer_rating",
        "audience_rating",
        "rt_release_month",
        "rt_url",
        "poster_url",
    ]
    if not RT_MANUAL_OVERRIDE_PATH.exists():
        return pd.DataFrame(columns=columns + ["film_key"])

    df = pd.read_csv(RT_MANUAL_OVERRIDE_PATH)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = df["film"].map(clean_film_key)
    return df[columns + ["film_key"]]


def read_tmdb_future_pool_candidates() -> pd.DataFrame:
    frames = []
    for path in sorted(RAW_DIR.glob(TMDB_POOL_GLOB)):
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"Skipping TMDb pool {path}: {exc}")
            continue

        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
        if "title" not in df.columns:
            continue

        if "release_date" in df.columns:
            release_date = pd.to_datetime(df["release_date"], errors="coerce")
            year_film = release_date.dt.year
            release_month = release_date.dt.month
        else:
            match = re.search(r"tmdb_movies_(\d{4})\.csv$", path.name)
            inferred_year = int(match.group(1)) if match else None
            year_film = pd.Series(inferred_year, index=df.index, dtype="float64")
            release_month = pd.Series(pd.NA, index=df.index)

        candidate_df = pd.DataFrame(
            {
                "year_film": pd.to_numeric(year_film, errors="coerce"),
                "film": df["title"].astype(str).str.strip(),
                "release_month": pd.to_numeric(release_month, errors="coerce"),
            }
        )
        candidate_df = candidate_df[
            candidate_df["year_film"].notna()
            & candidate_df["film"].ne("")
            & candidate_df["film"].ne("nan")
        ].copy()
        frames.append(candidate_df)

    if not frames:
        return pd.DataFrame(columns=["year_film", "film", "release_month"])

    return pd.concat(frames, ignore_index=True)


def build_rt_refresh_candidates(manifest: pd.DataFrame) -> pd.DataFrame:
    candidate_frames = []

    if OSCARS_PATH.exists():
        oscars = pd.read_csv(OSCARS_PATH, usecols=["year_film", "canon_category", "film"])
        oscars["year_film"] = pd.to_numeric(oscars["year_film"], errors="coerce")
        historical = oscars[
            oscars["canon_category"].astype(str).str.upper().eq("BEST PICTURE")
            & oscars["film"].notna()
            & oscars["year_film"].ge(RT_REFRESH_START_YEAR)
        ][["year_film", "film"]].copy()
        historical["release_month"] = pd.NA
        candidate_frames.append(historical)

    if not manifest.empty:
        manifest_candidates = manifest.copy()
        manifest_candidates["year_film"] = pd.to_numeric(manifest_candidates["year_film"], errors="coerce")
        manifest_candidates = manifest_candidates[manifest_candidates["film"].notna()].copy()
        if "release_month" not in manifest_candidates.columns:
            manifest_candidates["release_month"] = pd.NA
        candidate_frames.append(manifest_candidates[["year_film", "film", "release_month"]])

    tmdb_candidates = read_tmdb_future_pool_candidates()
    if not tmdb_candidates.empty:
        candidate_frames.append(tmdb_candidates)

    if not candidate_frames:
        return pd.DataFrame(columns=["year_film", "film", "release_month"])

    candidates = pd.concat(candidate_frames, ignore_index=True)
    candidates["film"] = candidates["film"].astype(str).str.strip()
    candidates = candidates[candidates["film"].ne("")].copy()
    candidates["film_key"] = candidates["film"].map(clean_film_key)
    candidates["release_month"] = pd.to_numeric(candidates["release_month"], errors="coerce")
    candidates["release_month_priority"] = candidates["release_month"].notna().astype(int)
    candidates = candidates.sort_values(
        ["year_film", "film_key", "release_month_priority"],
        ascending=[True, True, False],
    )
    candidates = candidates.drop_duplicates(subset=["year_film", "film_key"], keep="first")
    return candidates[["year_film", "film", "release_month"]]


def build_rt_summary(
    rt_cache_df: pd.DataFrame,
    wikipedia_rt_df: pd.DataFrame,
    manual_overrides_df: pd.DataFrame,
) -> pd.DataFrame:
    summary_frames = []

    if not wikipedia_rt_df.empty:
        wiki = wikipedia_rt_df.copy()
        wiki["source_priority"] = 1
        summary_frames.append(wiki)

    if not rt_cache_df.empty:
        cache_rows = rt_cache_df[rt_cache_df["status"] == "matched"].copy()
        cache_rows["rt_release_month"] = pd.to_numeric(cache_rows["release_month"], errors="coerce")
        cache_rows["film_key"] = cache_rows["film"].map(clean_film_key)
        cache_rows["source_priority"] = 2
        summary_frames.append(
            cache_rows[
                [
                    "year_film",
                    "film",
                    "film_key",
                    "tomatometer_rating",
                    "audience_rating",
                    "rt_release_month",
                    "rt_url",
                    "poster_url",
                    "source_priority",
                ]
            ]
        )

    if not manual_overrides_df.empty:
        manual = manual_overrides_df.copy()
        manual["source_priority"] = 3
        summary_frames.append(
            manual[
                [
                    "year_film",
                    "film",
                    "film_key",
                    "tomatometer_rating",
                    "audience_rating",
                    "rt_release_month",
                    "rt_url",
                    "poster_url",
                    "source_priority",
                ]
            ]
        )

    if not summary_frames:
        return pd.DataFrame(
            columns=[
                "year_film",
                "film",
                "tomatometer_rating",
                "audience_rating",
                "rt_release_month",
                "rt_url",
                "poster_url",
            ]
        )

    summary = pd.concat(summary_frames, ignore_index=True, sort=False)
    summary["year_film"] = pd.to_numeric(summary["year_film"], errors="coerce")
    summary["film_key"] = summary["film_key"].fillna(summary["film"].map(clean_film_key))
    summary["tomatometer_rating"] = pd.to_numeric(summary["tomatometer_rating"], errors="coerce")
    summary["audience_rating"] = pd.to_numeric(summary["audience_rating"], errors="coerce")
    summary["rt_release_month"] = pd.to_numeric(summary["rt_release_month"], errors="coerce")
    summary["score_present"] = summary["tomatometer_rating"].notna().astype(int)
    summary["url_present"] = summary["rt_url"].notna().astype(int)
    summary["poster_present"] = summary["poster_url"].notna().astype(int)
    summary = summary.sort_values(
        ["year_film", "film_key", "score_present", "url_present", "poster_present", "source_priority"],
        ascending=[True, True, False, False, False, False],
    )
    summary = summary.drop_duplicates(subset=["year_film", "film_key"], keep="first")
    summary = summary.sort_values(["year_film", "film"])
    return summary[
        [
            "year_film",
            "film",
            "tomatometer_rating",
            "audience_rating",
            "rt_release_month",
            "rt_url",
            "poster_url",
        ]
    ]


def row_to_film_candidate(row: pd.Series) -> Optional[str]:
    film_like_columns = [
        "film",
        "work",
        "works",
        "motion_picture",
        "picture",
        "program",
        "title",
        "show",
    ]
    for column in film_like_columns:
        if column in row.index:
            value = normalize_text(row[column])
            if value and len(value) > 1:
                return value

    if "nominee" in row.index:
        nominee = normalize_text(row["nominee"])
        if nominee and nominee == nominee.title():
            return nominee

    return None


def row_is_winner(row: pd.Series, row_index: int, table: pd.DataFrame) -> bool:
    lowered = {column.lower(): column for column in table.columns}
    result_column = next((lowered[col] for col in lowered if "result" in col or "status" in col), None)
    if result_column:
        result_text = normalize_text(row[result_column]).lower()
        return any(token in result_text for token in ["winner", "won", "yes"])

    if len(table) <= 10:
        return row_index == 0
    return False


def extract_award_rows(table: pd.DataFrame) -> list[tuple[str, bool]]:
    cleaned = table.copy()
    cleaned.columns = [normalize_text(column).lower().replace(" ", "_") for column in cleaned.columns]

    useful_columns = {
        "film",
        "work",
        "works",
        "motion_picture",
        "picture",
        "program",
        "title",
        "show",
        "nominee",
        "result",
        "status",
    }
    if not useful_columns.intersection(set(cleaned.columns)):
        return []

    rows = []
    for idx, row in cleaned.iterrows():
        film = row_to_film_candidate(row)
        if not film:
            continue
        rows.append((film, row_is_winner(row, idx, cleaned)))
    return rows


def refresh_awards_sources() -> dict:
    manifest = read_awards_manifest()
    results = {}

    for award_name in AWARD_OUTPUT_MAP:
        nom_column, win_column = AWARD_COLUMN_MAP[award_name]
        rows = []
        award_entries = [entry for entry in manifest if entry.get("award") == award_name]

        for entry in award_entries:
            try:
                tables = fetch_tables(entry["url"])
                time.sleep(0.5)
            except Exception as exc:
                print(f"Skipping {award_name} source {entry['url']}: {exc}")
                continue

            counts = {}
            for table in tables:
                for film, is_winner in extract_award_rows(table):
                    film_key = clean_film_key(film)
                    if not film_key:
                        continue
                    stats = counts.setdefault(film_key, {"film": film, nom_column: 0, win_column: 0})
                    stats[nom_column] += 1
                    if is_winner:
                        stats[win_column] += 1

            for film_key, stats in counts.items():
                rows.append(
                    {
                        "year_film": entry["year_film"],
                        "film": stats["film"],
                        nom_column: stats[nom_column],
                        win_column: stats[win_column],
                    }
                )

        df = pd.DataFrame(rows)
        if not df.empty:
            df["film_key"] = df["film"].map(clean_film_key)
            df = (
                df.sort_values(["year_film", nom_column, win_column], ascending=[True, False, False])
                .drop_duplicates(subset=["year_film", "film_key"], keep="first")
                .drop(columns=["film_key"])
                .sort_values(["year_film", "film"])
            )
            AWARD_OUTPUT_MAP[award_name].parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(AWARD_OUTPUT_MAP[award_name], index=False)
        results[award_name] = {"rows": len(df), "path": str(AWARD_OUTPUT_MAP[award_name])}

    return results


def refresh_film_sources() -> dict:
    manifest = read_film_manifest()
    rt_candidates = build_rt_refresh_candidates(manifest)
    rt_cache_df = refresh_rt_match_cache(rt_candidates, RT_CACHE_PATH) if not rt_candidates.empty else pd.DataFrame()
    manual_rt_df = read_rt_manual_overrides()
    wiki_rt_rows = []
    festival_rows = []
    future_rows = []

    for _, row in manifest.iterrows():
        wikipedia_title = row.get("wikipedia_title")
        if not wikipedia_title or pd.isna(wikipedia_title):
            continue

        try:
            text = extract_page_extract(str(wikipedia_title))
            time.sleep(1)
        except Exception as exc:
            print(f"Skipping film source {wikipedia_title}: {exc}")
            continue

        if not text:
            continue

        year_film = int(row["year_film"])
        film = row["film"]
        metacritic_score = parse_metacritic_score(text)
        tomatometer_rating = parse_tomatometer_score(text)
        manifest_release_month = pd.to_numeric(row.get("release_month"), errors="coerce")
        parsed_release_month = parse_release_month(text, year_film)
        release_month = (
            int(manifest_release_month)
            if pd.notna(manifest_release_month)
            else parsed_release_month
        )
        festival_flags = parse_festival_flags(text)

        festival_rows.append(
            {
                "year_film": year_film,
                "film": film,
                "metacritic_score": metacritic_score,
                **festival_flags,
            }
        )

        wiki_rt_rows.append(
            {
                "year_film": year_film,
                "film": film,
                "film_key": clean_film_key(film),
                "tomatometer_rating": tomatometer_rating,
                "audience_rating": pd.NA,
                "rt_release_month": release_month,
                "rt_url": pd.NA,
                "poster_url": pd.NA,
            }
        )

        future_rows.append(
            {
                "year_film": year_film,
                "film": film,
                "release_month": release_month,
                "metacritic_score": metacritic_score,
                **festival_flags,
                "manual_contender_flag": int(row.get("manual_contender_flag", 1)),
                "notes": f"Auto-refreshed from Wikipedia page {wikipedia_title}",
                "wikipedia_title": wikipedia_title,
            }
        )

    wikipedia_rt_df = pd.DataFrame(
        wiki_rt_rows,
        columns=[
            "year_film",
            "film",
            "film_key",
            "tomatometer_rating",
            "audience_rating",
            "rt_release_month",
            "rt_url",
            "poster_url",
        ],
    )
    rt_df = build_rt_summary(rt_cache_df, wikipedia_rt_df, manual_rt_df)
    festival_df = pd.DataFrame(
        festival_rows,
        columns=[
            "year_film",
            "film",
            "metacritic_score",
            "cannes_flag",
            "venice_flag",
            "tiff_flag",
            "telluride_flag",
            "sundance_flag",
            "sxsw_flag",
        ],
    )
    future_df = pd.DataFrame(
        future_rows,
        columns=[
            "year_film",
            "film",
            "release_month",
            "metacritic_score",
            "cannes_flag",
            "venice_flag",
            "tiff_flag",
            "telluride_flag",
            "sundance_flag",
            "sxsw_flag",
            "manual_contender_flag",
            "notes",
            "wikipedia_title",
        ],
    )

    if not rt_df.empty:
        rt_df = rt_df.sort_values(["year_film", "film"])
    if not festival_df.empty:
        festival_df = festival_df.sort_values(["year_film", "film"])
    if not future_df.empty:
        future_df = future_df.sort_values(["year_film", "film"])

    for path, df in [
        (RT_OUTPUT_PATH, rt_df),
        (FESTIVAL_OUTPUT_PATH, festival_df),
        (FUTURE_ENRICHMENT_OUTPUT_PATH, future_df),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)

    return {
        "rows": len(future_df),
        "rt_path": str(RT_OUTPUT_PATH),
        "festival_path": str(FESTIVAL_OUTPUT_PATH),
        "future_path": str(FUTURE_ENRICHMENT_OUTPUT_PATH),
    }


def run(skip_awards: bool = False, skip_films: bool = False) -> dict:
    report = {"awards": {}, "films": {}}
    if not skip_awards:
        report["awards"] = refresh_awards_sources()
    if not skip_films:
        report["films"] = refresh_film_sources()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Refresh awards, RT, festival, and Metacritic summary files from external source manifests."
    )
    parser.add_argument("--skip-awards", action="store_true", help="Skip awards-source refresh.")
    parser.add_argument("--skip-films", action="store_true", help="Skip film-source refresh.")
    args = parser.parse_args()
    summary = run(skip_awards=args.skip_awards, skip_films=args.skip_films)
    print(json.dumps(summary, indent=2))
