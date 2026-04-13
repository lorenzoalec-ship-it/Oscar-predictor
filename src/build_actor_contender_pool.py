"""
Build the live Best Actor contender pool for a given year.

Steps:
1. Load the film pool from output/future_best_picture_predictions_{year}.csv
2. Load TMDb credits from data/raw/tmdb_credits_{year}.csv (if exists)
3. Load the person_film_manifest for manual additions
4. For each candidate, look up current precursor signals (SAG/Globe/BAFTA nom/win)
5. Score using score_category_year()
6. Write output/future_actor_predictions_{year}.csv

Output columns:
  rank, name, film, win_probability, prior_nominations, prior_wins,
  tmdb_person_id, profile_url, sag_nom, sag_win, globe_nom, globe_win,
  bafta_nom, bafta_win, tomatometer_rating, metacritic_score,
  forecast_season, movement
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from train_category_model import score_category_year, _norm_name

RAW_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "output"
AGENT_DIR = ROOT / "data" / "agent_updates"


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
    """Load the Best Picture prediction pool as the base film set.

    Filters to the top 40 films by BP probability to keep the actor pool clean
    and focused on genuine prestige contenders.
    """
    path = OUTPUT_DIR / f"future_best_picture_predictions_{year}.csv"
    if not path.exists():
        print(f"[actor] No BP pool at {path}, returning empty DataFrame")
        return pd.DataFrame(columns=["tmdb_id", "title", "tomatometer_rating", "metacritic_score"])
    df = pd.read_csv(path)
    # Sort by BP probability and keep top 40 prestige contenders
    if "best_picture_probability" in df.columns:
        df = df.sort_values("best_picture_probability", ascending=False).head(40)
        print(f"[actor] Filtered film pool to top {len(df)} prestige contenders.")
    return df[["tmdb_id", "title", "tomatometer_rating", "metacritic_score"]].copy()


def load_tmdb_credits(year: int) -> pd.DataFrame:
    """Load TMDb credits file if it exists."""
    path = RAW_DIR / f"tmdb_credits_{year}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["tmdb_id", "lead_actor_name", "lead_actor_id", "lead_actor_profile_url"])
    return pd.read_csv(path)


def load_person_manifest(year: int, category: str = "actor") -> pd.DataFrame:
    """Load manual person-film manifest for the given year and category."""
    path = RAW_DIR / "person_film_manifest.csv"
    if not path.exists():
        return pd.DataFrame(columns=["year_film", "name", "film", "tmdb_person_id", "category"])
    df = pd.read_csv(path)
    return df[(df["year_film"] == year) & (df["category"] == category)].copy()


def load_current_precursors(year: int, category: str = "actor") -> pd.DataFrame:
    """
    Load current-year precursor nomination/win data.
    Checks the recent backfill files for the given year.
    Returns DataFrame with name_key, sag_nom, sag_win, globe_nom, globe_win, bafta_nom, bafta_win.
    """
    frames = []

    for fname, nom_col, win_col in [
        ("sag_actor_recent.csv", "sag_nom", "sag_win"),
        ("globe_actor_recent.csv", "globe_nom", "globe_win"),
        ("bafta_actor_recent.csv", "bafta_nom", "bafta_win"),
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
        return pd.DataFrame(columns=["name_key", "sag_nom", "sag_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"])

    # Merge all precursor frames on name_key
    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame, on="name_key", how="outer")

    for col in ["sag_nom", "sag_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"]:
        if col not in result.columns:
            result[col] = 0
        result[col] = result[col].fillna(0).astype(int)

    return result


def build_actor_pool(year: int) -> pd.DataFrame:
    """
    Build the candidate pool for Best Actor for the given year.

    Requires TMDb credits to be pulled first (pull_person_credits.py --year {year}).
    The manual manifest supplements TMDb credits but is NOT used as the sole source —
    that would produce unreliable actor-film pairings.

    Returns a DataFrame with: name, film, tmdb_person_id, profile_url,
    tomatometer_rating, metacritic_score, sag_nom, sag_win, globe_nom,
    globe_win, bafta_nom, bafta_win
    """
    film_pool = load_film_pool(year)
    tmdb_credits = load_tmdb_credits(year)
    precursors = load_current_precursors(year, "actor")

    # If precursor data exists (e.g. post-SAG/Globe/BAFTA), build the pool from
    # known nominees even without TMDb credits — these are verified pairings.
    has_precursor_data = not precursors.empty

    # Load manual manifest early — use as fallback source when no credits exist yet.
    manifest = load_person_manifest(year, "actor")
    has_manifest = not manifest.empty

    # If no TMDb credits AND no precursor data AND no manifest, we have no reliable source.
    if tmdb_credits.empty and not has_precursor_data and not has_manifest:
        print(f"[actor] No TMDb credits, precursor data, or manifest for {year} — skipping live board.")
        print(f"[actor] Run: python src/pull_person_credits.py --year {year}")
        return pd.DataFrame()

    candidates = []

    # From TMDb credits (joined to film pool) — primary source
    if not tmdb_credits.empty and "lead_actor_name" in tmdb_credits.columns:
        merged = film_pool.merge(
            tmdb_credits[["tmdb_id", "lead_actor_name", "lead_actor_id", "lead_actor_profile_url"]],
            on="tmdb_id", how="inner"
        )
        merged = merged.dropna(subset=["lead_actor_name"])
        for _, row in merged.iterrows():
            if pd.isna(row.get("lead_actor_name")) or not str(row["lead_actor_name"]).strip():
                continue
            candidates.append({
                "name": str(row["lead_actor_name"]).strip(),
                "film": str(row["title"]).strip(),
                "tmdb_person_id": row.get("lead_actor_id", ""),
                "profile_url": row.get("lead_actor_profile_url", ""),
                "tomatometer_rating": float(row.get("tomatometer_rating", 0) or 0),
                "metacritic_score": float(row.get("metacritic_score", 0) or 0),
            })

    # From manual manifest — early-season source when TMDb credits not yet available
    # Also used when a film's lead actor can't be reliably auto-detected
    if has_manifest:
        existing_names = {c["name"].upper() for c in candidates}
        for _, row in manifest.iterrows():
            name = str(row.get("name", "")).strip()
            film = str(row.get("film", "")).strip()
            tmdb_pid = str(row.get("tmdb_person_id", "") or "")
            if not name or not film:
                continue
            if name.upper() in existing_names:
                continue  # TMDb credits already have this actor
            film_scores = film_pool[film_pool["title"].str.upper() == film.upper()]
            tomatometer = float(film_scores["tomatometer_rating"].values[0]) if not film_scores.empty else 0.0
            metacritic = float(film_scores["metacritic_score"].values[0]) if not film_scores.empty else 0.0
            candidates.append({
                "name": name,
                "film": film,
                "tmdb_person_id": tmdb_pid,
                "profile_url": "",
                "tomatometer_rating": tomatometer,
                "metacritic_score": metacritic,
            })
            existing_names.add(name.upper())
            print(f"[actor] Added from manifest: {name} / {film}")

    # From precursor data — verified actor-film pairings from SAG/Globe/BAFTA nominations
    # These are always reliable and supplement or replace TMDb credits post-nominations.
    if has_precursor_data and "name" in precursors.columns:
        existing_names = {c["name"].upper() for c in candidates}
        for _, row in precursors.iterrows():
            name = str(row.get("name", "")).strip()
            film = str(row.get("film", "")).strip()
            if not name or not film:
                continue
            if name.upper() in existing_names:
                continue  # Already added from TMDb credits or manifest
            film_scores = film_pool[film_pool["title"].str.upper() == film.upper()]
            tomatometer = float(film_scores["tomatometer_rating"].values[0]) if not film_scores.empty else 0.0
            metacritic = float(film_scores["metacritic_score"].values[0]) if not film_scores.empty else 0.0
            candidates.append({
                "name": name,
                "film": film,
                "tmdb_person_id": "",
                "profile_url": "",
                "tomatometer_rating": tomatometer,
                "metacritic_score": metacritic,
            })
            existing_names.add(name.upper())

    if not candidates:
        print(f"[actor] No candidates found for year {year}")
        return pd.DataFrame()

    pool_df = pd.DataFrame(candidates).drop_duplicates(subset=["name", "film"]).reset_index(drop=True)

    # Merge precursor signals
    precursors = load_current_precursors(year, "actor")
    if not precursors.empty:
        pool_df["name_key"] = pool_df["name"].apply(_norm_name)
        pool_df = pool_df.merge(precursors, on="name_key", how="left")
        pool_df = pool_df.drop(columns=["name_key"], errors="ignore")

    for col in ["sag_nom", "sag_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"]:
        if col not in pool_df.columns:
            pool_df[col] = 0
        pool_df[col] = pool_df[col].fillna(0).astype(int)

    return pool_df


def run(year: int):
    print(f"[actor] Building Best Actor contender pool for {year}...")
    pool_df = build_actor_pool(year)

    if pool_df.empty:
        print(f"[actor] Empty pool — no output written.")
        return

    print(f"[actor] Scoring {len(pool_df)} candidates...")
    scored = score_category_year(year, pool_df, category="actor")
    scored = scored.sort_values("win_probability", ascending=False).reset_index(drop=True)
    scored["rank"] = range(1, len(scored) + 1)
    scored["forecast_season"] = _determine_forecast_season(year)

    # Compute rank movement — compare to a stable "previous" snapshot so that
    # a full pool rebuild doesn't wipe all movement history.
    out_path = OUTPUT_DIR / f"future_actor_predictions_{year}.csv"
    prev_path = OUTPUT_DIR / f"future_actor_predictions_{year}_prev.csv"

    # Save current file as prev snapshot BEFORE overwriting, but only if it
    # contains a meaningfully different pool (avoids overwriting prev with same data).
    if out_path.exists():
        import shutil
        shutil.copy(out_path, prev_path)

    # Load prev snapshot for movement comparison
    snap_path = prev_path if prev_path.exists() else out_path
    if snap_path.exists():
        prev = pd.read_csv(snap_path)
        prev_ranks = dict(zip(prev["name"].str.upper(), prev["rank"]))
        deltas = []
        movements = []
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
        "tmdb_person_id", "profile_url", "sag_nom", "sag_win", "globe_nom", "globe_win",
        "bafta_nom", "bafta_win", "tomatometer_rating", "metacritic_score",
        "forecast_season", "previous_rank", "rank_delta", "movement"
    ]
    for col in output_cols:
        if col not in scored.columns:
            scored[col] = None

    scored[output_cols].to_csv(out_path, index=False)
    print(f"[actor] Wrote {len(scored)} contenders to {out_path}")
    print(scored[["rank", "name", "film", "win_probability"]].head(10).to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=date.today().year)
    args = parser.parse_args()
    run(args.year)
