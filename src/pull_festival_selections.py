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
ENRICHMENT_PATH = RAW_DIR / "future_contender_enrichment.csv"

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
) -> tuple[list[dict], list[str]]:
    """
    Fuzzy-match extracted festival titles against the TMDb pool.

    Returns:
      matched  — list of dicts for films already in the pool
      new_titles — list of raw title strings NOT in the pool (pre-release picks)
    """
    pool_norms: dict[str, str] = {}
    if not pool_df.empty:
        pool_df = pool_df.copy()
        pool_df["title_norm"] = pool_df["title"].astype(str).apply(normalize_title)
        pool_norms = dict(zip(pool_df["title_norm"], pool_df["title"]))

    festival_norm = {normalize_title(t): t for t in festival_titles if t.strip()}
    matched: list[dict] = []
    new_titles: list[str] = []

    for norm_ft, raw_ft in festival_norm.items():
        if len(norm_ft) < 3:
            continue

        found_in_pool = False

        # Exact match first
        if norm_ft in pool_norms:
            matched.append({
                "year_film": year,
                "title": pool_norms[norm_ft],
                flag_col: 1,
                "notes": "Auto-detected from Wikipedia festival page",
                "_source_title": raw_ft,
            })
            found_in_pool = True
            continue

        # Partial match
        if not pool_df.empty:
            for _, row in pool_df.iterrows():
                pt = row["title_norm"]
                if len(pt) < 4:
                    continue
                if pt in norm_ft or norm_ft in pt:
                    ratio = min(len(pt), len(norm_ft)) / max(len(pt), len(norm_ft))
                    if ratio >= 0.7:
                        matched.append({
                            "year_film": year,
                            "title": row["title"],
                            flag_col: 1,
                            "notes": f"Auto-detected (partial match: '{raw_ft}')",
                            "_source_title": raw_ft,
                        })
                        found_in_pool = True
                        break

        # Not in pool — record as a new pre-release contender
        if not found_in_pool:
            new_titles.append(raw_ft)

    return matched, new_titles


def extract_competition_titles(html: str) -> set[str]:
    """
    Extract only film titles from wikitable competition sections.
    Looks for <i> text inside <td> cells — the standard Wikipedia format for film titles.
    Filters aggressively to avoid noise (director names, awards, countries, etc.).
    """
    import html as html_lib

    # Find all wikitable rows
    td_italic = re.compile(
        r'<td[^>]*>\s*(?:<[^>]+>\s*)*<i>(?:<[^>]+>)?(.*?)(?:</[^>]+>)?</i>', re.DOTALL
    )
    titles: set[str] = set()
    for m in td_italic.finditer(html):
        raw = m.group(1)
        clean = re.sub(r"<[^>]+>", "", raw).strip()
        clean = html_lib.unescape(clean)
        # Must look like a film title: 2–80 chars, no newlines, not all caps
        if 2 <= len(clean) <= 80 and "\n" not in clean and not clean.isupper():
            titles.add(clean)

    return titles


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


def load_existing_enrichment() -> pd.DataFrame:
    """Load the future contender enrichment file."""
    if ENRICHMENT_PATH.exists():
        return pd.read_csv(ENRICHMENT_PATH)
    return pd.DataFrame(columns=[
        "year_film", "film", "release_month", "metacritic_score",
        "cannes_flag", "venice_flag", "tiff_flag", "telluride_flag",
        "sundance_flag", "sxsw_flag", "manual_contender_flag", "notes", "wikipedia_title",
    ])


# Festival flag → enrichment column name
_FEST_FLAG_TO_ENRICH_COL = {
    "sundance_flag":  "sundance_flag",
    "berlin_flag":    None,               # Berlin not in enrichment schema yet
    "sxsw_flag":      "sxsw_flag",
    "cannes_flag":    "cannes_flag",
    "venice_flag":    "venice_flag",
    "telluride_flag": "telluride_flag",
    "tiff_flag":      "tiff_flag",
    "nyff_flag":      None,
    "afi_flag":       None,
}

# Estimated release month for a film premiering at each festival (typical wide-release timing)
_FEST_TO_RELEASE_MONTH = {
    "sundance_flag":  2,
    "berlin_flag":    4,
    "sxsw_flag":      4,
    "cannes_flag":    10,
    "venice_flag":    11,
    "telluride_flag": 11,
    "tiff_flag":      11,
    "nyff_flag":      11,
    "afi_flag":       11,
}


def pull_festival_selections(year: int):
    print(f"[festivals] Scraping festival Wikipedia pages for {year}...")

    pool_df = load_pool(year)
    print(f"[festivals] Pool has {len(pool_df)} films to match against.")

    existing = load_existing_flags()
    confirmed_key = set(
        zip(existing["year_film"].astype(str), existing["title"].str.lower().str.strip())
    ) if not existing.empty else set()

    existing_enrich = load_existing_enrichment()
    enrich_keys = set(
        existing_enrich[existing_enrich["year_film"] == year]["film"]
        .str.lower().str.strip()
    ) if not existing_enrich.empty else set()

    new_flag_rows: list[dict] = []
    new_enrich_rows: list[dict] = []

    for fest in festival_wikipedia_titles(year):
        flag_col = fest["flag"]
        wiki_title = fest["title"]
        print(f"\n[festivals] Checking: {wiki_title}")

        # Try HTML (richer structure), fall back to plaintext
        html = fetch_wikipedia_html(wiki_title)
        if html:
            # Use targeted competition-table extractor first, then broad extractor
            titles = extract_competition_titles(html)
            if len(titles) < 3:
                titles = extract_film_titles_from_html(html)
            print(f"  → Extracted {len(titles)} candidate titles from HTML")
        else:
            text = fetch_wikipedia_text(wiki_title)
            titles = extract_film_titles_from_text(text)
            print(f"  → Extracted {len(titles)} candidate titles from plaintext")

        if not titles:
            print(f"  → Page not found or empty (festival may not have announced yet)")
            continue

        matched, new_titles = match_titles_to_pool(titles, pool_df, flag_col, year)
        print(f"  → Matched {len(matched)} in pool, {len(new_titles)} new pre-release films")

        # --- Handle pool-matched films ---
        for m in matched:
            key = (str(year), m["title"].lower().strip())
            if key not in confirmed_key:
                print(f"    ✓ {m['title']} ({flag_col})")
                row = {"year_film": year, "title": m["title"], "notes": m["notes"]}
                for fc in FLAG_COLS:
                    row[fc] = 1 if fc == flag_col else 0
                new_flag_rows.append(row)
                confirmed_key.add(key)
            else:
                mask = (
                    (existing["year_film"] == year)
                    & (existing["title"].str.lower().str.strip() == m["title"].lower().strip())
                )
                if mask.any() and existing.loc[mask, flag_col].values[0] == 0:
                    existing.loc[mask, flag_col] = 1
                    print(f"    ↑ Updated {m['title']} → {flag_col}=1")

        # --- Handle pre-release films not yet in pool ---
        # Add to both flags AND enrichment so they get scored by the BP model
        for raw_title in new_titles:
            title_low = raw_title.lower().strip()
            key = (str(year), title_low)

            # Add to festival flags
            if key not in confirmed_key:
                row = {"year_film": year, "title": raw_title, "notes": f"Pre-release — {wiki_title}"}
                for fc in FLAG_COLS:
                    row[fc] = 1 if fc == flag_col else 0
                new_flag_rows.append(row)
                confirmed_key.add(key)
                print(f"    🆕 {raw_title} (pre-release, {flag_col})")

            # Add to enrichment so the scoring pipeline can include it
            enrich_col = _FEST_FLAG_TO_ENRICH_COL.get(flag_col)
            if enrich_col and title_low not in enrich_keys:
                enrich_row: dict = {
                    "year_film": year,
                    "film": raw_title,
                    "release_month": _FEST_TO_RELEASE_MONTH.get(flag_col, 10),
                    "metacritic_score": "",
                    "cannes_flag": 0,
                    "venice_flag": 0,
                    "tiff_flag": 0,
                    "telluride_flag": 0,
                    "sundance_flag": 0,
                    "sxsw_flag": 0,
                    "manual_contender_flag": 1,
                    "notes": f"Auto-added from {wiki_title}",
                    "wikipedia_title": "",
                }
                if enrich_col in enrich_row:
                    enrich_row[enrich_col] = 1
                new_enrich_rows.append(enrich_row)
                enrich_keys.add(title_low)

        time.sleep(0.5)

    # --- Write festival flags ---
    if new_flag_rows:
        new_df = pd.DataFrame(new_flag_rows)
        for fc in FLAG_COLS:
            if fc not in new_df.columns:
                new_df[fc] = 0
        updated = pd.concat([existing, new_df], ignore_index=True)
    else:
        updated = existing

    if not updated.empty:
        flag_agg = {fc: "max" for fc in FLAG_COLS}
        flag_agg["notes"] = "last"
        updated = updated.groupby(["year_film", "title"], as_index=False).agg(flag_agg)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    updated.to_csv(OUTPUT_PATH, index=False)
    total_flagged = len(updated[updated[FLAG_COLS].sum(axis=1) > 0]) if not updated.empty else 0
    print(f"\n[festivals] Flags saved: {total_flagged} films. → {OUTPUT_PATH}")

    # --- Write enrichment ---
    if new_enrich_rows:
        enrich_new_df = pd.DataFrame(new_enrich_rows)
        updated_enrich = pd.concat([existing_enrich, enrich_new_df], ignore_index=True)
        updated_enrich.to_csv(ENRICHMENT_PATH, index=False)
        print(f"[festivals] Enrichment saved: {len(new_enrich_rows)} new films. → {ENRICHMENT_PATH}")
    else:
        print(f"[festivals] No new enrichment entries.")


def main():
    parser = argparse.ArgumentParser(description="Pull festival selections from Wikipedia")
    parser.add_argument("--year", type=int, required=True, help="Eligibility year (e.g. 2026)")
    args = parser.parse_args()
    pull_festival_selections(args.year)


if __name__ == "__main__":
    main()
