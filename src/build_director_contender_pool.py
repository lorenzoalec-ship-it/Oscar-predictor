"""
Build the live Best Director contender pool for a given year.

Steps:
1. Load the film pool from output/future_best_picture_predictions_{year}.csv
2. Load TMDb credits from data/raw/tmdb_credits_{year}.csv (if exists)
3. Load the person_film_manifest for manual additions
4. For each candidate, look up current precursor signals (DGA/Globe/BAFTA nom/win)
5. Score using score_category_year()
6. Write output/future_director_predictions_{year}.csv

Output columns:
  rank, name, film, win_probability, prior_nominations, prior_wins,
  tmdb_person_id, profile_url, dga_nom, dga_win, globe_nom, globe_win,
  bafta_nom, bafta_win, tomatometer_rating, metacritic_score,
  forecast_season, previous_rank, rank_delta, movement
"""

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from train_category_model import score_category_year, _norm_name

RAW_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "output"

# Genre IDs that make Best Director contention extremely unlikely
# (documentaries have their own directing category; animation rarely crosses over)
EXCLUDED_GENRES = {
    99,     # Documentary — separate Oscar category
    10402,  # Music / Concert film
}


def _determine_forecast_season(year: int) -> str:
    today = date.today()
    month = today.month
    if today.year < year or (today.year == year and month < 9):
        return "early"
    elif month < 12:
        return "pre_precursor"
    else:
        return "precursor_nominations"


def load_film_pool(year: int) -> pd.DataFrame:
    path = OUTPUT_DIR / f"future_best_picture_predictions_{year}.csv"
    if not path.exists():
        print(f"[director] No BP pool at {path}, returning empty DataFrame")
        return pd.DataFrame(columns=["tmdb_id", "title", "tomatometer_rating", "metacritic_score"])
    df = pd.read_csv(path)

    if "genre_ids" in df.columns:
        def _is_eligible(genre_str):
            if pd.isna(genre_str) or not str(genre_str).strip():
                return True
            genres = {int(g.strip()) for g in str(genre_str).split(",") if g.strip().isdigit()}
            return not genres.intersection(EXCLUDED_GENRES)
        before = len(df)
        df = df[df["genre_ids"].apply(_is_eligible)].copy()
        removed = before - len(df)
        if removed:
            print(f"[director] Excluded {removed} films with Documentary/Concert genres.")

    if "best_picture_probability" in df.columns:
        df = df.sort_values("best_picture_probability", ascending=False).head(40)
        print(f"[director] Filtered film pool to top {len(df)} prestige contenders.")
    return df[["tmdb_id", "title", "tomatometer_rating", "metacritic_score"]].copy()


def load_tmdb_credits(year: int) -> pd.DataFrame:
    path = RAW_DIR / f"tmdb_credits_{year}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["tmdb_id", "director_name", "director_id", "director_profile_url"])
    return pd.read_csv(path)


def load_person_manifest(year: int) -> pd.DataFrame:
    path = RAW_DIR / "person_film_manifest.csv"
    if not path.exists():
        return pd.DataFrame(columns=["year_film", "name", "film", "tmdb_person_id", "category"])
    df = pd.read_csv(path)
    return df[(df["year_film"] == year) & (df["category"] == "director")].copy()


def load_current_precursors(year: int) -> pd.DataFrame:
    """Load DGA, Globe, and BAFTA director precursor data."""
    frames = []
    for fname, nom_col, win_col in [
        ("dga_director_recent.csv", "dga_nom", "dga_win"),
        ("globe_director_recent.csv", "globe_nom", "globe_win"),
        ("bafta_director_recent.csv", "bafta_nom", "bafta_win"),
    ]:
        path = RAW_DIR / fname
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df = df[df["year_film"] == year]
        if df.empty:
            continue
        df["name_key"] = df["name"].apply(_norm_name)
        frames.append(df[["name_key", nom_col, win_col]])

    if not frames:
        return pd.DataFrame(columns=["name_key", "dga_nom", "dga_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"])

    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame, on="name_key", how="outer")

    for col in ["dga_nom", "dga_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"]:
        if col not in result.columns:
            result[col] = 0
        result[col] = result[col].fillna(0).astype(int)

    return result


def build_director_pool(year: int) -> pd.DataFrame:
    film_pool = load_film_pool(year)
    tmdb_credits = load_tmdb_credits(year)
    precursors = load_current_precursors(year)
    manifest = load_person_manifest(year)

    has_precursor_data = not precursors.empty
    has_manifest = not manifest.empty

    if tmdb_credits.empty and not has_precursor_data and not has_manifest:
        print(f"[director] No TMDb credits, precursor data, or manifest for {year} — skipping.")
        print(f"[director] Run: python src/pull_person_credits.py --year {year}")
        return pd.DataFrame()

    candidates = []

    # Primary source: TMDb credits
    if not tmdb_credits.empty and "director_name" in tmdb_credits.columns:
        merged = film_pool.merge(
            tmdb_credits[["tmdb_id", "director_name", "director_id", "director_profile_url"]],
            on="tmdb_id", how="inner"
        )
        merged = merged.dropna(subset=["director_name"])
        for _, row in merged.iterrows():
            if pd.isna(row.get("director_name")) or not str(row["director_name"]).strip():
                continue
            candidates.append({
                "name": str(row["director_name"]).strip(),
                "film": str(row["title"]).strip(),
                "tmdb_person_id": row.get("director_id", ""),
                "profile_url": row.get("director_profile_url", ""),
                "tomatometer_rating": float(row.get("tomatometer_rating", 0) or 0),
                "metacritic_score": float(row.get("metacritic_score", 0) or 0),
            })

    # Manual manifest
    if has_manifest:
        existing_names = {c["name"].upper() for c in candidates}
        for _, row in manifest.iterrows():
            name = str(row.get("name", "")).strip()
            film = str(row.get("film", "")).strip()
            if not name or not film or name.upper() in existing_names:
                continue
            film_scores = film_pool[film_pool["title"].str.upper() == film.upper()]
            candidates.append({
                "name": name,
                "film": film,
                "tmdb_person_id": str(row.get("tmdb_person_id", "") or ""),
                "profile_url": "",
                "tomatometer_rating": float(film_scores["tomatometer_rating"].values[0]) if not film_scores.empty else 0.0,
                "metacritic_score": float(film_scores["metacritic_score"].values[0]) if not film_scores.empty else 0.0,
            })
            existing_names.add(name.upper())
            print(f"[director] Added from manifest: {name} / {film}")

    # Precursor nominees
    if has_precursor_data and "name" in precursors.columns:
        existing_names = {c["name"].upper() for c in candidates}
        for _, row in precursors.iterrows():
            name = str(row.get("name", "")).strip()
            film = str(row.get("film", "")).strip()
            if not name or not film or name.upper() in existing_names:
                continue
            film_scores = film_pool[film_pool["title"].str.upper() == film.upper()]
            candidates.append({
                "name": name,
                "film": film,
                "tmdb_person_id": "",
                "profile_url": "",
                "tomatometer_rating": float(film_scores["tomatometer_rating"].values[0]) if not film_scores.empty else 0.0,
                "metacritic_score": float(film_scores["metacritic_score"].values[0]) if not film_scores.empty else 0.0,
            })
            existing_names.add(name.upper())

    if not candidates:
        print(f"[director] No candidates found for year {year}")
        return pd.DataFrame()

    pool_df = pd.DataFrame(candidates).drop_duplicates(subset=["name", "film"]).reset_index(drop=True)

    # Merge precursor signals (DGA for director instead of SAG)
    if not precursors.empty:
        pool_df["name_key"] = pool_df["name"].apply(_norm_name)
        pool_df = pool_df.merge(precursors, on="name_key", how="left")
        pool_df = pool_df.drop(columns=["name_key"], errors="ignore")

    for col in ["dga_nom", "dga_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"]:
        if col not in pool_df.columns:
            pool_df[col] = 0
        pool_df[col] = pool_df[col].fillna(0).astype(int)

    return pool_df


def run(year: int):
    print(f"[director] Building Best Director contender pool for {year}...")
    pool_df = build_director_pool(year)

    if pool_df.empty:
        print(f"[director] Empty pool — no output written.")
        return

    print(f"[director] Scoring {len(pool_df)} candidates...")
    scored = score_category_year(year, pool_df, category="director")
    scored = scored.sort_values("win_probability", ascending=False).reset_index(drop=True)
    scored["rank"] = range(1, len(scored) + 1)
    scored["forecast_season"] = _determine_forecast_season(year)

    out_path = OUTPUT_DIR / f"future_director_predictions_{year}.csv"
    prev_path = OUTPUT_DIR / f"future_director_predictions_{year}_prev.csv"

    if out_path.exists():
        shutil.copy(out_path, prev_path)

    snap_path = prev_path if prev_path.exists() else out_path
    if snap_path.exists():
        prev = pd.read_csv(snap_path)
        prev_ranks = dict(zip(prev["name"].str.upper(), prev["rank"]))
        deltas, movements = [], []
        for _, row in scored.iterrows():
            key = row["name"].upper()
            prev_rank = prev_ranks.get(key)
            if prev_rank is None:
                deltas.append(None)
                movements.append("new")
            else:
                delta = prev_rank - row["rank"]
                deltas.append(delta)
                movements.append("up" if delta > 0 else "down" if delta < 0 else "same")
        scored["previous_rank"] = [prev_ranks.get(n.upper()) for n in scored["name"]]
        scored["rank_delta"] = deltas
        scored["movement"] = movements
    else:
        scored["previous_rank"] = None
        scored["rank_delta"] = None
        scored["movement"] = "new"

    output_cols = [
        "rank", "name", "film", "win_probability", "prior_nominations", "prior_wins",
        "tmdb_person_id", "profile_url", "dga_nom", "dga_win", "globe_nom", "globe_win",
        "bafta_nom", "bafta_win", "tomatometer_rating", "metacritic_score",
        "forecast_season", "previous_rank", "rank_delta", "movement"
    ]
    for col in output_cols:
        if col not in scored.columns:
            scored[col] = None

    scored[output_cols].to_csv(out_path, index=False)
    print(f"[director] Wrote {len(scored)} contenders to {out_path}")
    print(scored[["rank", "name", "film", "win_probability"]].head(10).to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=date.today().year)
    args = parser.parse_args()
    run(args.year)
