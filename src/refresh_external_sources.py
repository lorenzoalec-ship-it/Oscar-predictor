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
AWARDS_MANIFEST_PATH = AGENT_UPDATES_DIR / "awards_wikipedia_manifest.json"
FILM_MANIFEST_PATH = AGENT_UPDATES_DIR / "film_wikipedia_manifest.csv"

GLOBES_OUTPUT_PATH = AGENT_UPDATES_DIR / "golden_globe_recent_summary.csv"
SAG_OUTPUT_PATH = AGENT_UPDATES_DIR / "sag_recent_summary.csv"
BAFTA_OUTPUT_PATH = AGENT_UPDATES_DIR / "bafta_recent_summary.csv"
PGA_OUTPUT_PATH = AGENT_UPDATES_DIR / "pga_recent_summary.csv"
DGA_OUTPUT_PATH = AGENT_UPDATES_DIR / "dga_recent_summary.csv"
CRITICS_CHOICE_OUTPUT_PATH = AGENT_UPDATES_DIR / "critics_choice_recent_summary.csv"
RT_OUTPUT_PATH = AGENT_UPDATES_DIR / "rotten_tomatoes_recent_summary.csv"
FESTIVAL_OUTPUT_PATH = AGENT_UPDATES_DIR / "festival_metacritic_summary.csv"
FUTURE_ENRICHMENT_OUTPUT_PATH = AGENT_UPDATES_DIR / "future_contender_enrichment.csv"

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
    return normalize_text(value).lower()


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
    if manifest.empty:
        return {"rows": 0, "rt_path": str(RT_OUTPUT_PATH), "festival_path": str(FESTIVAL_OUTPUT_PATH), "future_path": str(FUTURE_ENRICHMENT_OUTPUT_PATH)}

    rt_rows = []
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

        rt_rows.append(
            {
                "year_film": year_film,
                "film": film,
                "tomatometer_rating": tomatometer_rating,
                "audience_rating": pd.NA,
                "rt_release_month": release_month,
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

    rt_df = pd.DataFrame(
        rt_rows,
        columns=["year_film", "film", "tomatometer_rating", "audience_rating", "rt_release_month"],
    )
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
