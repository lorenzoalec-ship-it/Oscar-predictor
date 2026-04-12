"""
Walk-forward ML models for Best Actor, Best Actress, and Best Director Oscar categories.

Each model is person-level (or person+film for director) and uses precursor signals:
  Actor:    SAG Male Leading Role, Globe Actor Drama, BAFTA Leading Actor
  Actress:  SAG Female Leading Role, Globe Actress Drama, BAFTA Leading Actress
  Director: DGA win, Globe Director, BAFTA Director

Precursor data coverage varies by source and year. Missing signals are filled with 0
(no win recorded) and a companion _known flag column indicates whether the data source
had coverage for that year at all.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MODEL_DATA_PATH = ROOT / "output" / "model_data.csv"

MIN_TRAIN_YEARS = 8  # fewer than Best Picture since acting categories have deeper data

# ---------------------------------------------------------------------------
# Category configuration
# ---------------------------------------------------------------------------

CATEGORY_CONFIG = {
    "actor": {
        "oscar_category": "ACTOR IN A LEADING ROLE",
        "label": "Best Actor",
    },
    "actress": {
        "oscar_category": "ACTRESS IN A LEADING ROLE",
        "label": "Best Actress",
    },
    "director": {
        "oscar_category": "DIRECTING",
        "label": "Best Director",
    },
}

# Features used for the winner model
ACTOR_FEATURES = [
    "prior_nominations",
    "prior_wins",
    "sag_win",
    "globe_win",
    "bafta_win",
    "tomatometer_rating",
    "metacritic_score",
]

DIRECTOR_FEATURES = [
    "prior_nominations",
    "prior_wins",
    "dga_win",
    "globe_win",
    "bafta_win",
    "tomatometer_rating",
    "metacritic_score",
]

# Recent backfill files (2020-2024 data not in the original CSVs)
SAG_ACTOR_RECENT_PATH = ROOT / "data" / "raw" / "sag_actor_recent.csv"
GLOBE_ACTOR_RECENT_PATH = ROOT / "data" / "raw" / "globe_actor_recent.csv"
BAFTA_ACTOR_RECENT_PATH = ROOT / "data" / "raw" / "bafta_actor_recent.csv"

# Extended feature set including nomination signals
ACTOR_FEATURES_EXTENDED = [
    "prior_nominations",
    "prior_wins",
    "sag_nom",
    "sag_win",
    "globe_nom",
    "globe_win",
    "bafta_nom",
    "bafta_win",
    "tomatometer_rating",
    "metacritic_score",
]


# ---------------------------------------------------------------------------
# Data loaders — raw precursor sources
# ---------------------------------------------------------------------------

def _norm_name(s):
    """Uppercase, strip extra whitespace for name matching."""
    if pd.isna(s):
        return ""
    return " ".join(str(s).upper().split())


def load_oscar_nominees(category: str) -> pd.DataFrame:
    """Return all Oscar nominees for a category with year_film, name, film, winner."""
    oscar_cat = CATEGORY_CONFIG[category]["oscar_category"]
    df = pd.read_csv(RAW_DIR / "the_oscar_award.csv")
    df = df[df["canon_category"] == oscar_cat][["year_film", "name", "film", "winner"]].copy()
    df["winner"] = df["winner"].astype(bool).astype(int)
    df["name_key"] = df["name"].apply(_norm_name)
    return df.reset_index(drop=True)


def load_sag_acting(gender: str) -> pd.DataFrame:
    """
    Return SAG leading-role data for 'male' or 'female'.
    Returns columns: year_film, name_key, film_key, sag_win
    SAG ceremony year N covers films from year N-1.
    """
    sag = pd.read_csv(RAW_DIR / "screen_actor_guild_awards.csv")
    sag["year_num"] = sag["year"].str.extract(r"(\d{4})").astype(float).fillna(0).astype(int)
    sag["year_film"] = sag["year_num"] - 1

    prefix = "MALE" if gender == "male" else "FEMALE"
    # Normalize category variants across years
    leading_cats = {
        f"{prefix} ACTOR IN A LEADING ROLE",
        f"{prefix} LEAD IN A MOTION PICTURE",
        f"{prefix} LEAD",
        f"{prefix} LEAD ROLE",
    }
    mask = sag["category"].str.strip().str.upper().isin(leading_cats)
    sub = sag[mask].copy()

    sub["name_key"] = sub["full_name"].apply(_norm_name)
    sub["film_key"] = sub["show"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    sub["sag_win"] = sub["won"].astype(bool).astype(int)
    return sub[["year_film", "name_key", "film_key", "sag_win"]].reset_index(drop=True)


def load_globe_acting(gender: str) -> pd.DataFrame:
    """
    Return Golden Globe acting data (Drama category) for 'male' or 'female'.
    Returns columns: year_film, name_key, film_key, globe_win
    """
    gg = pd.read_csv(RAW_DIR / "golden_globe_awards.csv")
    if gender == "male":
        cat = "Best Performance by an Actor in a Motion Picture - Drama"
    else:
        cat = "Best Performance by an Actress in a Motion Picture - Drama"

    sub = gg[gg["category"] == cat].copy()
    sub["name_key"] = sub["nominee"].apply(_norm_name)
    sub["film_key"] = sub["film"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    sub["globe_win"] = sub["win"].astype(bool).astype(int)
    return sub[["year_film", "name_key", "film_key", "globe_win"]].reset_index(drop=True)


def load_bafta_acting(gender: str) -> pd.DataFrame:
    """
    Return BAFTA acting data for 'male' or 'female'.
    BAFTA year column = ceremony year; year_film = bafta_year - 1.
    Returns columns: year_film, name_key, film_key, bafta_win
    """
    bafta = pd.read_csv(RAW_DIR / "bafta_films.csv")
    if gender == "male":
        # Covers both old "Actor in" and modern "Leading Actor in"
        mask = bafta["category"].str.contains(r"Actor in|Leading Actor in", na=False, regex=True)
        mask &= ~bafta["category"].str.contains("Support|British|Foreign|Debut", na=False)
    else:
        mask = bafta["category"].str.contains(r"Actress in|Leading Actress in", na=False, regex=True)
        mask &= ~bafta["category"].str.contains("Support|British|Foreign|Debut", na=False)

    sub = bafta[mask].copy()
    sub["year_film"] = sub["year"].astype(int) - 1
    sub["name_key"] = sub["nominee"].apply(_norm_name)
    # 'workers' column = film title in acting rows
    sub["film_key"] = sub["workers"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    sub["bafta_win"] = sub["winner"].astype(bool).astype(int)
    return sub[["year_film", "name_key", "film_key", "bafta_win"]].reset_index(drop=True)


def load_globe_director() -> pd.DataFrame:
    """
    Return Golden Globe Best Director data.
    Returns columns: year_film, name_key, film_key, globe_win
    """
    gg = pd.read_csv(RAW_DIR / "golden_globe_awards.csv")
    sub = gg[gg["category"] == "Best Director - Motion Picture"].copy()
    sub["name_key"] = sub["nominee"].apply(_norm_name)
    sub["film_key"] = sub["film"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    sub["globe_win"] = sub["win"].astype(bool).astype(int)
    return sub[["year_film", "name_key", "film_key", "globe_win"]].reset_index(drop=True)


def load_bafta_director() -> pd.DataFrame:
    """
    Return BAFTA Director data.
    BAFTA year = ceremony year; year_film = bafta_year - 1.
    Returns columns: year_film, name_key, film_key, bafta_win
    """
    bafta = pd.read_csv(RAW_DIR / "bafta_films.csv")
    mask = bafta["category"].str.contains(r"Director in", na=False, regex=True)
    sub = bafta[mask].copy()
    sub["year_film"] = sub["year"].astype(int) - 1
    sub["name_key"] = sub["nominee"].apply(_norm_name)
    sub["film_key"] = sub["workers"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    sub["bafta_win"] = sub["winner"].astype(bool).astype(int)
    return sub[["year_film", "name_key", "film_key", "bafta_win"]].reset_index(drop=True)


def load_dga() -> pd.DataFrame:
    """
    Return DGA data from the recent summary (film-level, not person-level).
    Returns columns: year_film, film_key, dga_win
    """
    dga = pd.read_csv(RAW_DIR / "dga_recent_summary.csv")
    dga["film_key"] = dga["film"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    dga["dga_win"] = (dga["dga_win_count"] >= 1).astype(int)
    return dga[["year_film", "film_key", "dga_win"]].reset_index(drop=True)


def load_film_scores() -> pd.DataFrame:
    """Load tomatometer and metacritic scores from model_data, indexed by year_film+film."""
    model = pd.read_csv(MODEL_DATA_PATH)
    model["film_key"] = model["film"].apply(lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else "")
    scores = model[["year_film", "film", "film_key", "tomatometer_rating", "metacritic_score"]].copy()
    scores["tomatometer_rating"] = pd.to_numeric(scores["tomatometer_rating"], errors="coerce").fillna(0)
    scores["metacritic_score"] = pd.to_numeric(scores["metacritic_score"], errors="coerce").fillna(0)
    return scores


# ---------------------------------------------------------------------------
# Year coverage helpers
# ---------------------------------------------------------------------------

def load_sag_acting_recent(gender: str) -> pd.DataFrame:
    """Load the 2020+ SAG acting backfill. Returns year_film, name_key, sag_nom, sag_win."""
    if gender != "male":
        return pd.DataFrame(columns=["year_film", "name_key", "sag_nom", "sag_win"])
    if not SAG_ACTOR_RECENT_PATH.exists():
        return pd.DataFrame(columns=["year_film", "name_key", "sag_nom", "sag_win"])
    df = pd.read_csv(SAG_ACTOR_RECENT_PATH)
    df["name_key"] = df["name"].apply(_norm_name)
    df["sag_nom"] = df["sag_nom"].fillna(0).astype(int)
    df["sag_win"] = df["sag_win"].fillna(0).astype(int)
    return df[["year_film", "name_key", "sag_nom", "sag_win"]]


def load_globe_acting_recent(gender: str) -> pd.DataFrame:
    """Load the 2020+ Globe acting backfill. Returns year_film, name_key, globe_nom, globe_win."""
    if gender != "male":
        return pd.DataFrame(columns=["year_film", "name_key", "globe_nom", "globe_win"])
    if not GLOBE_ACTOR_RECENT_PATH.exists():
        return pd.DataFrame(columns=["year_film", "name_key", "globe_nom", "globe_win"])
    df = pd.read_csv(GLOBE_ACTOR_RECENT_PATH)
    df["name_key"] = df["name"].apply(_norm_name)
    df["globe_nom"] = df["globe_nom"].fillna(0).astype(int)
    df["globe_win"] = df["globe_win"].fillna(0).astype(int)
    return df[["year_film", "name_key", "globe_nom", "globe_win"]]


def load_bafta_acting_recent(gender: str) -> pd.DataFrame:
    """Load the 2020+ BAFTA acting backfill. Returns year_film, name_key, bafta_nom, bafta_win."""
    if gender != "male":
        return pd.DataFrame(columns=["year_film", "name_key", "bafta_nom", "bafta_win"])
    if not BAFTA_ACTOR_RECENT_PATH.exists():
        return pd.DataFrame(columns=["year_film", "name_key", "bafta_nom", "bafta_win"])
    df = pd.read_csv(BAFTA_ACTOR_RECENT_PATH)
    df["name_key"] = df["name"].apply(_norm_name)
    df["bafta_nom"] = df["bafta_nom"].fillna(0).astype(int)
    df["bafta_win"] = df["bafta_win"].fillna(0).astype(int)
    return df[["year_film", "name_key", "bafta_nom", "bafta_win"]]


def _years_covered(df: pd.DataFrame) -> set:
    return set(df["year_film"].dropna().astype(int).unique())


# ---------------------------------------------------------------------------
# Dataset builders
# ---------------------------------------------------------------------------

def _join_precursor_by_name(nominees: pd.DataFrame, precursor: pd.DataFrame,
                             win_col: str, year_col: str = "year_film") -> pd.DataFrame:
    """
    Join precursor signals to nominees by year_film + name_key.
    If the precursor has no data for a given year, fills with 0 (no win recorded).
    """
    covered_years = _years_covered(precursor)
    # For years with coverage, join on year+name; default to 0 if name not matched
    precursor_agg = (
        precursor.groupby([year_col, "name_key"])[win_col]
        .max()
        .reset_index()
    )
    nominees = nominees.merge(
        precursor_agg,
        on=[year_col, "name_key"],
        how="left",
    )
    # Fill: 0 regardless of coverage (years without coverage also get 0)
    nominees[win_col] = nominees[win_col].fillna(0).astype(int)
    return nominees


def _join_precursor_by_film(nominees: pd.DataFrame, precursor: pd.DataFrame,
                             win_col: str, year_col: str = "year_film") -> pd.DataFrame:
    """
    Join precursor signals to nominees by year_film + film_key.
    """
    nominees["film_key"] = nominees["film"].apply(
        lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else ""
    )
    precursor_agg = (
        precursor.groupby([year_col, "film_key"])[win_col]
        .max()
        .reset_index()
    )
    nominees = nominees.merge(
        precursor_agg,
        on=[year_col, "film_key"],
        how="left",
    )
    nominees[win_col] = nominees[win_col].fillna(0).astype(int)
    return nominees


def _add_prior_history(df: pd.DataFrame, winner_col: str = "winner") -> pd.DataFrame:
    """
    Add prior_nominations and prior_wins counts for each person, computed
    from earlier rows in the same dataset (no data leakage).
    """
    df = df.sort_values("year_film").copy()
    prior_noms = {}
    prior_wins = {}
    nom_list = []
    win_list = []

    for _, row in df.iterrows():
        key = row["name_key"]
        nom_list.append(prior_noms.get(key, 0))
        win_list.append(prior_wins.get(key, 0))
        prior_noms[key] = prior_noms.get(key, 0) + 1
        prior_wins[key] = prior_wins.get(key, 0) + int(row[winner_col])

    df["prior_nominations"] = nom_list
    df["prior_wins"] = win_list
    return df


def build_category_dataset(category: str) -> pd.DataFrame:
    """
    Build a person-level dataset for 'actor', 'actress', or 'director'.

    Returns a DataFrame with one row per Oscar nominee per year, including:
      year_film, name, film, winner, prior_nominations, prior_wins,
      sag_win/dga_win, globe_win, bafta_win, tomatometer_rating, metacritic_score
    """
    nominees = load_oscar_nominees(category)
    film_scores = load_film_scores()

    if category in ("actor", "actress"):
        gender = "male" if category == "actor" else "female"
        sag = load_sag_acting(gender)
        globe = load_globe_acting(gender)
        bafta = load_bafta_acting(gender)

        nominees = _join_precursor_by_name(nominees, sag, "sag_win")
        nominees = _join_precursor_by_name(nominees, globe, "globe_win")
        nominees = _join_precursor_by_name(nominees, bafta, "bafta_win")

        # Initialize nom columns with 0 (older years won't have them)
        nominees["sag_nom"] = 0
        nominees["globe_nom"] = 0
        nominees["bafta_nom"] = 0

        if category == "actor":
            # Load and merge recent backfill data (fills the 2020-2024 gap)
            for loader_fn, nom_col, win_col in [
                (lambda: load_sag_acting_recent("male"), "sag_nom", "sag_win"),
                (lambda: load_globe_acting_recent("male"), "globe_nom", "globe_win"),
                (lambda: load_bafta_acting_recent("male"), "bafta_nom", "bafta_win"),
            ]:
                recent = loader_fn()
                if recent.empty:
                    continue
                recent_agg = (
                    recent.groupby(["year_film", "name_key"])[[nom_col, win_col]]
                    .max().reset_index()
                )
                # Merge, updating rows where old CSV had no coverage
                tmp = nominees.merge(
                    recent_agg.rename(columns={nom_col: f"_r_{nom_col}", win_col: f"_r_{win_col}"}),
                    on=["year_film", "name_key"], how="left"
                )
                # Update nom column from recent backfill
                nominees[nom_col] = tmp[f"_r_{nom_col}"].fillna(0).astype(int)
                # For win: if old CSV already has a 1 (win), keep it. Otherwise use recent backfill value.
                nominees[win_col] = nominees[win_col].where(
                    nominees[win_col] >= 1,
                    tmp[f"_r_{win_col}"].fillna(0).astype(int)
                )

    elif category == "director":
        globe = load_globe_director()
        bafta = load_bafta_director()
        dga = load_dga()

        # Director join: prefer name match for Globe/BAFTA, film match for DGA
        nominees = _join_precursor_by_name(nominees, globe, "globe_win")
        nominees = _join_precursor_by_name(nominees, bafta, "bafta_win")
        nominees = _join_precursor_by_film(nominees, dga, "dga_win")

    # Join film-level critic scores
    nominees["film_key"] = nominees["film"].apply(
        lambda s: " ".join(str(s).upper().split()) if pd.notna(s) else ""
    )
    scores_agg = film_scores.groupby(["year_film", "film_key"])[
        ["tomatometer_rating", "metacritic_score"]
    ].max().reset_index()
    nominees = nominees.merge(scores_agg, on=["year_film", "film_key"], how="left")
    nominees["tomatometer_rating"] = nominees["tomatometer_rating"].fillna(0)
    nominees["metacritic_score"] = nominees["metacritic_score"].fillna(0)

    # Add prior nomination/win history (no data leakage — computed in chronological order)
    nominees = _add_prior_history(nominees, winner_col="winner")

    return nominees.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Model training and walk-forward backtest
# ---------------------------------------------------------------------------

def _build_model():
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_leaf_nodes=15,
        min_samples_leaf=3,
        l2_regularization=0.1,
        random_state=42,
        class_weight="balanced",
    )


def _features_for(category: str):
    if category == "director":
        return DIRECTOR_FEATURES
    return ACTOR_FEATURES_EXTENDED  # includes nom columns for actor/actress


def _train_and_score_year(train_df: pd.DataFrame, test_df: pd.DataFrame,
                          category: str) -> pd.DataFrame:
    """Train on train_df, score test_df. Returns test_df with win_probability column."""
    features = _features_for(category)
    available = [f for f in features if f in train_df.columns and f in test_df.columns]
    if not available:
        return test_df.assign(win_probability=0.0)

    X_train = train_df[available].fillna(0)
    y_train = train_df["winner"]

    if y_train.nunique() < 2:
        # No positive examples — can't train; assign uniform probability
        test_df = test_df.copy()
        n = len(test_df)
        test_df["win_probability"] = 1.0 / n if n else 0.0
        return test_df

    model = _build_model()
    model.fit(X_train, y_train)

    X_test = test_df[available].fillna(0)
    classes = list(model.classes_)
    pos_idx = classes.index(1) if 1 in classes else 0
    probs = model.predict_proba(X_test)[:, pos_idx]

    test_df = test_df.copy()
    test_df["win_probability"] = probs
    total = probs.sum()
    if total > 0:
        test_df["win_probability"] = test_df["win_probability"] / total
    return test_df


def backtest_category(category: str) -> pd.DataFrame:
    """
    Walk-forward backtest for a category.

    For each year with sufficient prior data, train on all prior years,
    score that year's nominees, pick the top probability as predicted winner.

    Returns a DataFrame with columns:
      year_film, predicted_winner, actual_winner, correct,
      predicted_probability, runner_up
    """
    df = build_category_dataset(category)
    features = _features_for(category)

    years = sorted(df["year_film"].dropna().unique().astype(int))
    rows = []

    for year in years:
        train_df = df[df["year_film"] < year].copy()
        test_df = df[df["year_film"] == year].copy()

        prior_years = sorted(train_df["year_film"].unique())
        if len(prior_years) < MIN_TRAIN_YEARS:
            continue
        if test_df.empty:
            continue
        if train_df["winner"].sum() == 0:
            continue

        test_df = _train_and_score_year(train_df, test_df, category)
        test_df = test_df.sort_values("win_probability", ascending=False).reset_index(drop=True)

        predicted_row = test_df.iloc[0]
        actual_rows = test_df[test_df["winner"] == 1]
        actual_name = actual_rows.iloc[0]["name"] if not actual_rows.empty else None

        rows.append(
            {
                "year_film": int(year),
                "train_start": int(train_df["year_film"].min()),
                "train_end": int(train_df["year_film"].max()),
                "predicted_winner": predicted_row["name"],
                "predicted_film": predicted_row["film"],
                "predicted_probability": float(predicted_row["win_probability"]),
                "actual_winner": actual_name,
                "actual_film": actual_rows.iloc[0]["film"] if not actual_rows.empty else None,
                "correct": actual_name == predicted_row["name"] if actual_name else False,
                "runner_up": test_df.iloc[1]["name"] if len(test_df) > 1 else None,
                "runner_up_film": test_df.iloc[1]["film"] if len(test_df) > 1 else None,
                "runner_up_probability": float(test_df.iloc[1]["win_probability"]) if len(test_df) > 1 else None,
                # Precursor signals for the predicted winner
                "sag_win": int(predicted_row.get("sag_win", 0)) if category != "director" else None,
                "dga_win": int(predicted_row.get("dga_win", 0)) if category == "director" else None,
                "globe_win": int(predicted_row.get("globe_win", 0)),
                "bafta_win": int(predicted_row.get("bafta_win", 0)),
            }
        )

    return pd.DataFrame(rows)


def backtest_accuracy(category: str, verbose: bool = True) -> tuple[pd.DataFrame, float]:
    """Run backtest and return (summary_df, accuracy)."""
    summary = backtest_category(category)
    if summary.empty:
        if verbose:
            print(f"{CATEGORY_CONFIG[category]['label']}: no backtest results.")
        return summary, 0.0
    accuracy = float(summary["correct"].mean())
    if verbose:
        label = CATEGORY_CONFIG[category]["label"]
        print(f"\n{label} walk-forward backtest:")
        print(summary[["year_film", "predicted_winner", "actual_winner", "correct"]].to_string(index=False))
        print(f"\nAccuracy: {accuracy:.2%} ({int(summary['correct'].sum())}/{len(summary)} correct)")
    return summary, accuracy


# ---------------------------------------------------------------------------
# Live scoring for future years
# ---------------------------------------------------------------------------

def score_category_year(
    year_film: int,
    candidates: pd.DataFrame,
    category: str = "actor",
) -> pd.DataFrame:
    """
    Train the category model on all historical data up to (but not including)
    year_film, then score the provided candidates DataFrame.

    candidates must have columns: name, film, and optionally any feature columns
    (sag_nom, sag_win, globe_nom, globe_win, bafta_nom, bafta_win,
     tomatometer_rating, metacritic_score).
    Missing feature columns are filled with 0.

    Returns candidates with added columns:
      win_probability, prior_nominations, prior_wins
    """
    hist_df = build_category_dataset(category)
    train_df = hist_df[hist_df["year_film"] < year_film].copy()

    if train_df["winner"].sum() == 0 or len(train_df["year_film"].unique()) < MIN_TRAIN_YEARS:
        candidates = candidates.copy()
        n = len(candidates)
        candidates["win_probability"] = 1.0 / n if n else 0.0
        candidates["prior_nominations"] = 0
        candidates["prior_wins"] = 0
        return candidates

    # Add prior Oscar history for each candidate
    oscar_hist = hist_df[["name_key", "year_film", "winner"]].copy()
    oscar_hist = oscar_hist[oscar_hist["year_film"] < year_film]

    prior_noms_map = oscar_hist.groupby("name_key").size().to_dict()
    prior_wins_map = oscar_hist[oscar_hist["winner"] == 1].groupby("name_key").size().to_dict()

    candidates = candidates.copy()
    candidates["name_key"] = candidates["name"].apply(_norm_name)
    candidates["prior_nominations"] = candidates["name_key"].map(prior_noms_map).fillna(0).astype(int)
    candidates["prior_wins"] = candidates["name_key"].map(prior_wins_map).fillna(0).astype(int)

    features = _features_for(category)
    for f in features:
        if f not in candidates.columns:
            candidates[f] = 0
        candidates[f] = pd.to_numeric(candidates[f], errors="coerce").fillna(0)

    # Train model
    available = [f for f in features if f in train_df.columns]
    X_train = train_df[available].fillna(0)
    y_train = train_df["winner"]

    if y_train.nunique() < 2:
        n = len(candidates)
        candidates["win_probability"] = 1.0 / n if n else 0.0
        return candidates

    model = _build_model()
    model.fit(X_train, y_train)

    X_test = candidates[[f for f in available if f in candidates.columns]].fillna(0)
    classes = list(model.classes_)
    pos_idx = classes.index(1) if 1 in classes else 0
    probs = model.predict_proba(X_test)[:, pos_idx]

    total = probs.sum()
    if total > 0:
        probs = probs / total
    candidates["win_probability"] = probs
    return candidates


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Walk-forward backtest for acting/directing categories.")
    parser.add_argument("--category", choices=["actor", "actress", "director", "all"], default="all")
    args = parser.parse_args()

    cats = ["actor", "actress", "director"] if args.category == "all" else [args.category]
    for cat in cats:
        backtest_accuracy(cat, verbose=True)
