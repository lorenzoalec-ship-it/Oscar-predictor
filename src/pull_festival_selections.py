"""
pull_festival_selections.py

Automatically scrapes each major film festival's Wikipedia page for the current
eligibility year and extracts film selections. Matches them against our TMDb pool
and writes confirmed festival flags to data/raw/manual_festival_flags.csv.

No manual input required — runs weekly as part of the refresh workflow.

Festivals covered:
  Sundance, SXSW, Cannes, Venice, Telluride, TIFF

Wikipedia page patterns:
  Sundance:  "{year} Sundance Film Festival"
  SXSW:      "{year} South by Southwest"
  Cannes:    "{year} Cannes Film Festival"
  Venice:    "{edition}th/st/nd/rd Venice International Film Festival"
  Telluride: "{year} Telluride Film Festival"
  TIFF:      "{year} Toronto International Film Festival"
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_PATH = RAW_DIR / "manual_festival_flags.csv"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
REQUEST_HEADERS = {"User-Agent": "OscarPredictor/1.0 (festival-scraper; educational project)"}
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3

FLAG_COLS = [
    "sundance_flag", "berlin_flag", "sxsw_flag", "cannes_flag",
    "venice_flag", "telluride_flag", "tiff_flag", "nyff_flag", "afi_flag",
]

# Venice uses edition numbers, not years. 2025 = 82nd, so 2026 = 83rd, etc.
VENICE_BASE_YEAR = 2025
VENICE_BASE_EDITION = 82

ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ORDINAL_SUFFIXES.get(n % 10, 'th')}"


def festival_wikipedia_titles(year: int) -> list[dict]:
    venice_edition = VENICE_BASE_EDITION + (year - VENICE_BASE_YEAR)
    return [
        {"flag": "sundance_flag",  "title": f"{year} Sundance Film Festival"},
        {"flag": "berlin_flag",    "title": f"{year} Berlin International Film Festival"},
        {"flag": "sxsw_flag",      "title": f"{year} South by Southwest"},
        {"flag": "cannes_flag",    "title": f"{year} Cannes Film Festival"},
        {"flag": "venice_flag",    "title": f"{ordinal(venice_edition)} Venice International Film Festival"},
        {"flag": "telluride_flag", "title": f"{year} Telluride Film Festival"},
        {"flag": "tiff_flag",      "title": f"{year} Toronto International Film Festival"},
        {"flag": "nyff_flag",      "title": f"{year} New York Film Festival"},
        {"flag": "afi_flag",       "title": f"AFI Fest {year}"},
    ]


def _fetch_with_retry(url: str, params: str = "") -> bytes:
    full_url = f"{url}?{params}" if params else url
    req = Request(full_url, headers=REQUEST_HEADERS)
    last_exc = RuntimeError("No attempts made")
    for attempt in range(MAX_RETRIES):
        try:
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read()
        except (URLError, OSError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    raise last_exc


def fetch_wikipedia_text(page_title: str) -> str:
    """Fetch the plain-text extract of a Wikipedia page."""
    params = (
        f"action=query&titles={quote(page_title)}&prop=extracts"
        f"&explaintext=true&exsectionformat=plain&format=json"
    )
    try:
        raw = _fetch_with_retry(WIKIPEDIA_API, params)
        data = json.loads(raw)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if "missing" in page:
                return ""
            return page.get("extract", "")
    except Exception as exc:
        print(f"  [wiki] Failed to fetch '{page_title}': {exc}")
    return ""


def fetch_wikipedia_html(page_title: str) -> str:
    """Fetch the HTML of a Wikipedia page for table parsing."""
    params = (
        f"action=parse&page={quote(page_title)}&prop=text&format=json"
    )
    try:
        raw = _fetch_with_retry(WIKIPEDIA_API, params)
        data = json.loads(raw)
        return data.get("parse", {}).get("text", {}).get("*", "")
    except Exception as exc:
        print(f"  [wiki] Failed to fetch HTML for '{page_title}': {exc}")
    return ""


def extract_film_titles_from_text(text: str) -> set[str]:
    """
    Extract film titles from Wikipedia plaintext.
    Film titles in festival articles are typically in bold or listed in tables.
    We capture anything that looks like a quoted/bolded title.
    """
    titles = set()

    # Match italicised titles: ''Film Name'' in wikitext / plain text lines
    # In extract plaintext, titles often appear as standalone lines or after bullets
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        # Skip very short or very long lines, headers, and meta lines
        if not line or len(line) < 2 or len(line) > 120:
            continue
        if line.startswith("=") or line.startswith("{") or line.startswith("|"):
            continue
        # Lines that are just a film title (no verb, no period mid-sentence)
        # heuristic: ≤6 words, no lowercase connector words starting the line
        words = line.split()
        if 1 <= len(words) <= 8:
            # Exclude lines that look like section headers or descriptions
            if not any(line.lower().startswith(w) for w in
                       ["the film", "the story", "in the", "a film", "this ", "it ", "he ", "she "]):
                titles.add(line)

    return titles


def extract_film_titles_from_html(html: str) -> set[str]:
    """Parse film titles out of HTML tables on a festival Wikipedia page."""
    titles = set()
    if not html:
        return titles

    try:
        import html as html_lib
        # Find all table cells and list items that might contain film titles
        # Look for bold/italic text which typically marks film titles in festival articles
        patterns = [
            r"<i><b>(.*?)</b></i>",
            r"<b><i>(.*?)</i></b>",
            r"<i>(.*?)</i>",
            r"<b>(.*?)</b>",
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, html, re.DOTALL):
                raw = m.group(1)
                # Strip inner HTML tags
                clean = re.sub(r"<[^>]+>", "", raw).strip()
                clean = html_lib.unescape(clean)
                if 2 <= len(clean) <= 80 and "\n" not in clean:
                    titles.add(clean)
    except Exception as exc:
        print(f"  [html] Extraction error: {exc}")

    return titles


def normalize_title(t: str) -> str:
    """Lowercase, strip punctuation for fuzzy matching."""
    t = t.lower().strip()
    t = re.sub(r"[^a-z0-9 ]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def match_titles_to_pool(
    festival_titles: set[str],
    pool_df: pd.DataFrame,
    flag_col: str,
    year: int,
) -> list[dict]:
    """
    Fuzzy-match extracted festival titles against the TMDb pool.
    Returns list of matched rows with flag set.
    """
    if pool_df.empty:
        return []

    pool_df = pool_df.copy()
    pool_df["title_norm"] = pool_df["title"].astype(str).apply(normalize_title)

    festival_norm = {normalize_title(t): t for t in festival_titles if t.strip()}
    matched = []

    for norm_ft, raw_ft in festival_norm.items():
        if len(norm_ft) < 3:
            continue
        # Exact match first
        exact = pool_df[pool_df["title_norm"] == norm_ft]
        if not exact.empty:
            for _, row in exact.iterrows():
                matched.append({
                    "year_film": year,
                    "title": row["title"],
                    flag_col: 1,
                    "notes": f"Auto-detected from Wikipedia festival page",
                    "_source_title": raw_ft,
                })
            continue

        # Partial match: pool title fully contained in festival title or vice versa
        for _, row in pool_df.iterrows():
            pt = row["title_norm"]
            if len(pt) < 4:
                continue
            if pt in norm_ft or norm_ft in pt:
                # Only accept if the shorter string is at least 70% of the longer
                ratio = min(len(pt), len(norm_ft)) / max(len(pt), len(norm_ft))
                if ratio >= 0.7:
                    matched.append({
                        "year_film": year,
                        "title": row["title"],
                        flag_col: 1,
                        "notes": f"Auto-detected (partial match: '{raw_ft}')",
                        "_source_title": raw_ft,
                    })

    return matched


def load_pool(year: int) -> pd.DataFrame:
    """Load the TMDb movie pool for the year."""
    path = ROOT / "output" / f"future_best_picture_predictions_{year}.csv"
    if path.exists():
        df = pd.read_csv(path)
        if "title" in df.columns:
            return df[["title"]].drop_duplicates()
    # Fallback to raw tmdb movies
    path2 = RAW_DIR / f"tmdb_movies_{year}.csv"
    if path2.exists():
        df = pd.read_csv(path2)
        if "title" in df.columns:
            return df[["title"]].drop_duplicates()
    return pd.DataFrame(columns=["title"])


def load_existing_flags() -> pd.DataFrame:
    """Load the current manual festival flags file."""
    if OUTPUT_PATH.exists():
        df = pd.read_csv(OUTPUT_PATH)
        for col in FLAG_COLS:
            if col not in df.columns:
                df[col] = 0
        return df
    return pd.DataFrame(columns=["year_film", "title"] + FLAG_COLS + ["notes"])


def pull_festival_selections(year: int):
    print(f"[festivals] Scraping festival Wikipedia pages for {year}...")

    pool_df = load_pool(year)
    if pool_df.empty:
        print(f"[festivals] No film pool found for {year} — skipping.")
        return

    print(f"[festivals] Pool has {len(pool_df)} films to match against.")

    existing = load_existing_flags()
    # Track what's already confirmed so we don't duplicate
    confirmed_key = set(
        zip(existing["year_film"].astype(str), existing["title"].str.lower().str.strip())
    ) if not existing.empty else set()

    new_rows = []

    for fest in festival_wikipedia_titles(year):
        flag_col = fest["flag"]
        wiki_title = fest["title"]
        print(f"\n[festivals] Checking: {wiki_title}")

        # Try HTML first (richer structure for tables), fall back to plaintext
        html = fetch_wikipedia_html(wiki_title)
        if html:
            titles = extract_film_titles_from_html(html)
            print(f"  → Extracted {len(titles)} candidate titles from HTML")
        else:
            text = fetch_wikipedia_text(wiki_title)
            titles = extract_film_titles_from_text(text)
            print(f"  → Extracted {len(titles)} candidate titles from plaintext")

        if not titles:
            print(f"  → Page not found or empty (festival may not have announced yet)")
            continue

        matches = match_titles_to_pool(titles, pool_df, flag_col, year)
        print(f"  → Matched {len(matches)} films in our pool")

        for m in matches:
            key = (str(year), m["title"].lower().strip())
            if key not in confirmed_key:
                print(f"    ✓ {m['title']} ({flag_col})")
                row = {"year_film": year, "title": m["title"], "notes": m["notes"]}
                for fc in FLAG_COLS:
                    row[fc] = 1 if fc == flag_col else 0
                new_rows.append(row)
                confirmed_key.add(key)
            else:
                # Update the existing row's flag if not already set
                mask = (
                    (existing["year_film"] == year)
                    & (existing["title"].str.lower().str.strip() == m["title"].lower().strip())
                )
                if mask.any() and existing.loc[mask, flag_col].values[0] == 0:
                    existing.loc[mask, flag_col] = 1
                    print(f"    ↑ Updated {m['title']} → {flag_col}=1")

        time.sleep(0.5)  # Be polite to Wikipedia

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        for fc in FLAG_COLS:
            if fc not in new_df.columns:
                new_df[fc] = 0
        updated = pd.concat([existing, new_df], ignore_index=True)
    else:
        updated = existing

    # Deduplicate: group by year+title, take max of each flag
    if not updated.empty:
        flag_agg = {fc: "max" for fc in FLAG_COLS}
        flag_agg["notes"] = "last"
        updated = (
            updated.groupby(["year_film", "title"], as_index=False)
            .agg(flag_agg)
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    updated.to_csv(OUTPUT_PATH, index=False)
    total_flagged = len(updated[updated[FLAG_COLS].sum(axis=1) > 0]) if not updated.empty else 0
    print(f"\n[festivals] Done. {total_flagged} films flagged. Saved to {OUTPUT_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Pull festival selections from Wikipedia")
    parser.add_argument("--year", type=int, required=True, help="Eligibility year (e.g. 2026)")
    args = parser.parse_args()
    pull_festival_selections(args.year)


if __name__ == "__main__":
    main()
