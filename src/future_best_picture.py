import argparse
from datetime import date
import math
from pathlib import Path
from typing import Optional

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier


DATA_PATH = Path("output/model_data.csv")
DEFAULT_POOL_PATH_TEMPLATE = "data/raw/tmdb_movies_{year}.csv"
OUTPUT_PATH_TEMPLATE = "output/future_best_picture_predictions_{year}.csv"
FESTIVAL_METACRITIC_SUMMARY_PATH = Path("data/raw/festival_metacritic_summary.csv")
FUTURE_CONTENDER_ENRICHMENT_PATH = Path("data/raw/future_contender_enrichment.csv")
RT_RECENT_SUMMARY_PATH = Path("data/raw/rotten_tomatoes_recent_summary.csv")

TMDB_DRAMA_ID = "18"
TMDB_HISTORY_ID = "36"
TMDB_MUSIC_ID = "10402"
TMDB_WAR_ID = "10752"

MODEL_FEATURES = [
    "release_month",
    "tomatometer_rating",
    "metacritic_score",
    "movie_rating",
    "movie_vote_count_log",
    "is_drama",
    "is_history",
    "is_music",
    "is_war",
    "cannes_flag",
    "venice_flag",
    "tiff_flag",
    "telluride_flag",
    "sundance_flag",
    "sxsw_flag",
    "festival_presence_score",
]

WINNER_MODEL_FEATURES = MODEL_FEATURES + ["nominee_probability"]

SEASON_CONFIG = {
    "early": {
        "winner_model_weight": 0.15,
        "nominee_model_weight": 0.20,
        "prestige_weight": 0.55,
        "crowd_weight": 0.10,
    },
    "festival": {
        "winner_model_weight": 0.20,
        "nominee_model_weight": 0.25,
        "prestige_weight": 0.45,
        "crowd_weight": 0.10,
    },
    "precursor": {
        "winner_model_weight": 0.35,
        "nominee_model_weight": 0.25,
        "prestige_weight": 0.30,
        "crowd_weight": 0.10,
    },
    "post_nomination": {
        "winner_model_weight": 0.50,
        "nominee_model_weight": 0.20,
        "prestige_weight": 0.20,
        "crowd_weight": 0.10,
    },
}


def parse_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
        .replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def load_historical_data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def has_genre_token(series: pd.Series, token: str) -> pd.Series:
    return series.astype(str).str.contains(token, case=False, na=False).astype(int)


def has_genre_id(series: pd.Series, genre_id: str) -> pd.Series:
    pattern = rf"(?:^|,){genre_id}(?:,|$)"
    return series.astype(str).str.contains(pattern, regex=True, na=False).astype(int)


def get_series(df: pd.DataFrame, column: str, default=0) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def clip01(series: pd.Series) -> pd.Series:
    return series.fillna(0).clip(lower=0, upper=1)


def normalize(series: pd.Series, scale: float) -> pd.Series:
    if not scale:
        return pd.Series(0.0, index=series.index)
    return clip01(parse_numeric(series) / scale)


def infer_season(eligibility_year: int, override: Optional[str] = None) -> str:
    if override:
        return override

    today = date.today()
    if today.year < eligibility_year:
        return "early"
    if today.year > eligibility_year + 1:
        return "post_nomination"
    if today.year == eligibility_year + 1:
        if today.month <= 2:
            return "post_nomination"
        return "post_nomination"

    if today.month <= 6:
        return "early"
    if today.month <= 9:
        return "festival"
    if today.month <= 12:
        return "precursor"
    return "post_nomination"


def add_common_features(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    enriched["movie_vote_count"] = parse_numeric(get_series(enriched, "movie_vote_count")).fillna(0)
    enriched["movie_rating"] = parse_numeric(get_series(enriched, "movie_rating")).fillna(0)
    enriched["tomatometer_rating"] = parse_numeric(get_series(enriched, "tomatometer_rating")).fillna(0)
    enriched["metacritic_score"] = parse_numeric(get_series(enriched, "metacritic_score")).fillna(0)
    enriched["release_month"] = parse_numeric(get_series(enriched, "release_month")).fillna(0)
    enriched["movie_vote_count_log"] = enriched["movie_vote_count"].apply(
        lambda value: math.log1p(value) if value >= 0 else 0
    )

    if "movie_genres" in enriched.columns:
        genres = enriched["movie_genres"]
        enriched["is_drama"] = has_genre_token(genres, "Drama")
        enriched["is_history"] = has_genre_token(genres, "History")
        enriched["is_music"] = has_genre_token(genres, "Music")
        enriched["is_war"] = has_genre_token(genres, "War")
    elif "genres" in enriched.columns:
        genres = enriched["genres"]
        enriched["is_drama"] = has_genre_token(genres, "Drama")
        enriched["is_history"] = has_genre_token(genres, "History")
        enriched["is_music"] = has_genre_token(genres, "Music")
        enriched["is_war"] = has_genre_token(genres, "War")
    else:
        genre_ids = get_series(enriched, "genre_ids", default="")
        enriched["is_drama"] = has_genre_id(genre_ids, TMDB_DRAMA_ID)
        enriched["is_history"] = has_genre_id(genre_ids, TMDB_HISTORY_ID)
        enriched["is_music"] = has_genre_id(genre_ids, TMDB_MUSIC_ID)
        enriched["is_war"] = has_genre_id(genre_ids, TMDB_WAR_ID)

    for col in ["cannes_flag", "venice_flag", "tiff_flag", "telluride_flag", "sundance_flag", "sxsw_flag"]:
        enriched[col] = parse_numeric(get_series(enriched, col)).fillna(0)
    enriched["manual_contender_flag"] = parse_numeric(
        get_series(enriched, "manual_contender_flag")
    ).fillna(0).astype(int)
    enriched["festival_presence_score"] = (
        enriched["cannes_flag"]
        + enriched["venice_flag"]
        + enriched["tiff_flag"]
        + enriched["telluride_flag"]
        + enriched["sundance_flag"]
        + enriched["sxsw_flag"]
    )

    return enriched


def load_festival_metacritic_summary() -> pd.DataFrame:
    df = pd.read_csv(FESTIVAL_METACRITIC_SUMMARY_PATH)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = df["film"].astype(str).str.strip().str.lower()
    return df


def load_future_contender_enrichment() -> pd.DataFrame:
    df = pd.read_csv(FUTURE_CONTENDER_ENRICHMENT_PATH)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = df["film"].astype(str).str.strip().str.lower()
    return df


def load_recent_rt_summary() -> pd.DataFrame:
    df = pd.read_csv(RT_RECENT_SUMMARY_PATH)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = df["film"].astype(str).str.strip().str.lower()
    return df


def merge_festival_metacritic(df: pd.DataFrame, year_column: str, title_column: str) -> pd.DataFrame:
    summary = load_festival_metacritic_summary()
    enriched = df.copy()
    enriched["film_key"] = enriched[title_column].astype(str).str.strip().str.lower()
    enriched[year_column] = pd.to_numeric(enriched[year_column], errors="coerce")
    enriched = enriched.merge(
        summary.drop(columns=["film"]),
        left_on=[year_column, "film_key"],
        right_on=["year_film", "film_key"],
        how="left",
    )
    return enriched.drop(columns=["year_film"], errors="ignore")


def merge_future_enrichment(df: pd.DataFrame, eligibility_year: int) -> pd.DataFrame:
    summary = load_festival_metacritic_summary()
    future = load_future_contender_enrichment()
    rt_summary = load_recent_rt_summary()
    enriched = df.copy()
    enriched["year_film"] = pd.to_numeric(enriched["release_date"].dt.year, errors="coerce")
    enriched["film_key"] = enriched["title"].astype(str).str.strip().str.lower()

    enriched = enriched.merge(
        summary.drop(columns=["film"]),
        on=["year_film", "film_key"],
        how="left",
    )
    enriched = enriched.merge(
        future.drop(columns=["film"]),
        on=["year_film", "film_key"],
        how="left",
        suffixes=("", "_future"),
    )

    override_cols = [
        "metacritic_score",
        "cannes_flag",
        "venice_flag",
        "tiff_flag",
        "telluride_flag",
        "sundance_flag",
        "sxsw_flag",
        "release_month",
        "manual_contender_flag",
    ]
    for col in override_cols:
        future_col = f"{col}_future"
        if future_col in enriched.columns:
            overridden = enriched[future_col].notna().sum()
            if overridden:
                print(f"[merge_future_enrichment] Overriding '{col}' for {overridden} film(s) from future enrichment.")
            existing_col = (
                enriched[col]
                if col in enriched.columns
                else pd.Series(pd.NA, index=enriched.index, dtype="object")
            )
            enriched[col] = existing_col.where(enriched[future_col].isna(), enriched[future_col])

    future_only = future[future["year_film"] == eligibility_year].copy()
    existing_keys = set(enriched["film_key"].dropna().astype(str))
    future_only = future_only[~future_only["film_key"].isin(existing_keys)].copy()
    if not future_only.empty:
        future_only["title"] = future_only["film"]
        future_only["release_date"] = pd.to_datetime(
            future_only["year_film"].astype("Int64").astype(str)
            + "-"
            + future_only["release_month"].fillna(1).astype(int).astype(str).str.zfill(2)
            + "-01",
            errors="coerce",
        )
        future_only["movie_rating"] = 0
        future_only["movie_vote_count"] = 0
        future_only["genre_ids"] = ""
        future_only["poster_url"] = pd.NA
        future_only["poster_path"] = pd.NA
        future_only["backdrop_url"] = pd.NA
        future_only["backdrop_path"] = pd.NA
        future_only["overview"] = future_only.get("notes")
        future_only["manual_contender_flag"] = future_only["manual_contender_flag"].fillna(1)
        enriched = pd.concat([enriched, future_only], ignore_index=True, sort=False)

    enriched = enriched.merge(
        rt_summary.drop(columns=["film"]),
        on=["year_film", "film_key"],
        how="left",
        suffixes=("", "_rt"),
    )

    if "tomatometer_rating_rt" in enriched.columns:
        existing_rt = (
            pd.to_numeric(enriched["tomatometer_rating"], errors="coerce")
            if "tomatometer_rating" in enriched.columns
            else pd.Series(pd.NA, index=enriched.index, dtype="float64")
        )
        existing_rt = existing_rt.mask(existing_rt.eq(0), pd.NA)
        enriched["tomatometer_rating"] = pd.to_numeric(
            enriched["tomatometer_rating_rt"], errors="coerce"
        ).combine_first(existing_rt)

    if "audience_rating_rt" in enriched.columns:
        existing_audience = (
            pd.to_numeric(enriched["audience_rating"], errors="coerce")
            if "audience_rating" in enriched.columns
            else pd.Series(pd.NA, index=enriched.index, dtype="float64")
        )
        existing_audience = existing_audience.mask(existing_audience.eq(0), pd.NA)
        enriched["audience_rating"] = pd.to_numeric(
            enriched["audience_rating_rt"], errors="coerce"
        ).combine_first(existing_audience)

    if "rt_url_rt" in enriched.columns:
        existing_rt_url = (
            enriched["rt_url"]
            if "rt_url" in enriched.columns
            else pd.Series(pd.NA, index=enriched.index, dtype="object")
        )
        enriched["rt_url"] = enriched["rt_url_rt"].combine_first(existing_rt_url)

    if "rt_release_month_rt" in enriched.columns:
        existing_release_month = (
            pd.to_numeric(enriched["release_month"], errors="coerce")
            if "release_month" in enriched.columns
            else pd.Series(pd.NA, index=enriched.index, dtype="float64")
        )
        enriched["release_month"] = pd.to_numeric(
            enriched["rt_release_month_rt"], errors="coerce"
        ).combine_first(existing_release_month)

    if "poster_url_rt" in enriched.columns:
        existing_poster_url = (
            enriched["poster_url"]
            if "poster_url" in enriched.columns
            else pd.Series(pd.NA, index=enriched.index, dtype="object")
        )
        enriched["poster_url"] = existing_poster_url.combine_first(enriched["poster_url_rt"])

    drop_cols = [col for col in enriched.columns if col.endswith("_future") or col.endswith("_rt")]
    return enriched.drop(columns=drop_cols, errors="ignore")


def prepare_best_picture_training_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    model_df = add_common_features(df)
    model_df = model_df.dropna(subset=["release_month", "best_picture_winner", "best_picture_nominee"]).copy()
    X = model_df[MODEL_FEATURES].fillna(0)
    y = model_df["best_picture_nominee"].astype(int)
    return X, y


def train_early_best_picture_model(df: pd.DataFrame) -> dict:
    model_df = add_common_features(df)
    model_df = model_df.dropna(subset=["release_month", "best_picture_winner", "best_picture_nominee"]).copy()

    nominee_model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=15,
        min_samples_leaf=5,
        l2_regularization=0.1,
        random_state=42,
        class_weight="balanced",
    )
    nominee_model.fit(model_df[MODEL_FEATURES].fillna(0), model_df["best_picture_nominee"].astype(int))

    winner_df = model_df[model_df["best_picture_nominee"] == 1].copy()
    winner_df["nominee_probability"] = nominee_model.predict_proba(
        winner_df[MODEL_FEATURES].fillna(0)
    )[:, 1]

    winner_model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=15,
        min_samples_leaf=5,
        l2_regularization=0.1,
        random_state=42,
        class_weight="balanced",
    )
    winner_model.fit(
        winner_df[WINNER_MODEL_FEATURES].fillna(0),
        winner_df["best_picture_winner"].astype(int),
    )
    return {
        "nominee_model": nominee_model,
        "winner_model": winner_model,
    }


def load_future_pool(path: Path, eligibility_year: Optional[int] = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)

    if "title" not in df.columns:
        raise KeyError(f"Expected a 'title' column in {path}")

    if "release_date" not in df.columns:
        raise KeyError(f"Expected a 'release_date' column in {path}")

    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    df["release_month"] = df["release_date"].dt.month

    if "rating" in df.columns:
        df["movie_rating"] = parse_numeric(df["rating"])
    elif "vote_average" in df.columns:
        df["movie_rating"] = parse_numeric(df["vote_average"])
    else:
        df["movie_rating"] = 0

    if "no_of_persons_voted" in df.columns:
        df["movie_vote_count"] = parse_numeric(df["no_of_persons_voted"])
    elif "vote_count" in df.columns:
        df["movie_vote_count"] = parse_numeric(df["vote_count"])
    else:
        df["movie_vote_count"] = 0

    df["year_film"] = df["release_date"].dt.year
    if eligibility_year is None:
        if df["year_film"].dropna().empty:
            raise ValueError(f"Could not infer eligibility year from {path}")
        eligibility_year = int(df["year_film"].dropna().mode().iloc[0])
    df = merge_future_enrichment(df, eligibility_year)
    return add_common_features(df)


def build_candidate_pool(df: pd.DataFrame, eligibility_year: int) -> pd.DataFrame:
    base_pool = df[df["release_date"].dt.year.eq(eligibility_year)].copy()
    base_pool = base_pool[base_pool["title"].notna()].copy()

    manual_flag = parse_numeric(get_series(base_pool, "manual_contender_flag")).fillna(0).astype(int)
    pool = base_pool[
        manual_flag.eq(1)
        | (
            (base_pool["movie_vote_count"] >= 25)
            & (base_pool["movie_rating"] > 0)
            & base_pool["release_month"].notna()
        )
    ].copy()
    if pool.empty:
        pool = base_pool[manual_flag.eq(1) | base_pool["release_month"].notna()].copy()
    if pool.empty:
        pool = base_pool.copy()

    return pool.drop_duplicates(subset=["title"], keep="first")


def compute_prestige_score(scored: pd.DataFrame, season: str) -> pd.Series:
    release_month_score = clip01(
        pd.Series(0.0, index=scored.index)
        .mask(scored["release_month"].between(9, 12), 1.0)
        .mask(scored["release_month"].eq(8), 0.65)
        .mask(scored["release_month"].between(1, 4), 0.15)
    )
    metacritic_score = clip01(scored["metacritic_score"] / 100)
    festival_score = clip01(scored["festival_presence_score"] / 2)
    genre_score = clip01(
        (scored["is_drama"] * 0.6 + scored["is_history"] * 0.4 + scored["is_music"] * 0.2 + scored["is_war"] * 0.3)
        / 1.5
    )
    manual_score = clip01(scored["manual_contender_flag"])
    critic_score = clip01(scored["tomatometer_rating"] / 100)

    if season == "early":
        return (
            manual_score * 0.30
            + metacritic_score * 0.25
            + festival_score * 0.20
            + release_month_score * 0.15
            + genre_score * 0.10
        )
    if season == "festival":
        return (
            manual_score * 0.20
            + metacritic_score * 0.25
            + festival_score * 0.25
            + release_month_score * 0.15
            + genre_score * 0.10
            + critic_score * 0.05
        )
    if season == "precursor":
        return (
            manual_score * 0.10
            + metacritic_score * 0.25
            + festival_score * 0.20
            + release_month_score * 0.10
            + genre_score * 0.05
            + critic_score * 0.30
        )
    return (
        manual_score * 0.05
        + metacritic_score * 0.20
        + festival_score * 0.15
        + release_month_score * 0.05
        + genre_score * 0.05
        + critic_score * 0.50
    )


def score_candidates(model: dict, pool: pd.DataFrame, season: str) -> pd.DataFrame:
    if pool.empty:
        return pool

    scored = pool.copy()
    scored["nominee_probability"] = model["nominee_model"].predict_proba(
        scored[MODEL_FEATURES].fillna(0)
    )[:, 1]
    probs = model["winner_model"].predict_proba(
        scored[WINNER_MODEL_FEATURES].fillna(0)
    )[:, 1]
    scored["winner_model_probability"] = probs
    scored["prestige_score"] = compute_prestige_score(scored, season)
    scored["crowd_score"] = clip01(
        scored["movie_rating"] / 10 * 0.4 + normalize(scored["movie_vote_count_log"], math.log1p(5000)) * 0.6
    )

    config = SEASON_CONFIG[season]
    scored["best_picture_probability_raw"] = (
        scored["winner_model_probability"] * config["winner_model_weight"]
        + scored["nominee_probability"] * config["nominee_model_weight"]
        + scored["prestige_score"] * config["prestige_weight"]
        + scored["crowd_score"] * config["crowd_weight"]
    )
    total = scored["best_picture_probability_raw"].sum()
    if total > 0:
        scored["best_picture_probability"] = scored["best_picture_probability_raw"] / total
    else:
        scored["best_picture_probability"] = 0

    scored = scored.sort_values(
        ["best_picture_probability", "movie_vote_count", "movie_rating"],
        ascending=[False, False, False],
    )
    return scored


def run(eligibility_year: int, pool_path: Path, season: Optional[str] = None):
    historical_df = load_historical_data()
    model = train_early_best_picture_model(historical_df)
    active_season = infer_season(eligibility_year, season)

    future_pool = load_future_pool(pool_path, eligibility_year)
    candidates = build_candidate_pool(future_pool, eligibility_year)
    scored = score_candidates(model, candidates, active_season)
    scored["forecast_season"] = active_season

    output_path = Path(OUTPUT_PATH_TEMPLATE.format(year=eligibility_year))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(output_path, index=False)

    ceremony_year = eligibility_year + 1
    print(
        f"Top early Best Picture predictions for the {ceremony_year} Oscars "
        f"(eligible films released in {eligibility_year}):"
    )
    print(f"Season mode: {active_season}")

    if scored.empty:
        print("No candidates found in the future movie pool after filtering.")
        print(f"Checked pool file: {pool_path}")
        return scored

    preview_cols = [
        "title",
        "release_date",
        "metacritic_score",
        "movie_rating",
        "movie_vote_count",
        "festival_presence_score",
        "manual_contender_flag",
        "nominee_probability",
        "prestige_score",
        "is_drama",
        "is_history",
        "best_picture_probability",
    ]
    print(scored[preview_cols].head(20).to_string(index=False))
    print(f"\nSaved predictions to {output_path}")
    return scored


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate early Best Picture predictions for a future Oscars race.")
    parser.add_argument("--year", type=int, required=True, help="Eligibility year, for example 2026 for the 2027 Oscars.")
    parser.add_argument(
        "--pool",
        type=Path,
        default=None,
        help="CSV file with future movie releases. Defaults to data/raw/tmdb_movies_<year>.csv",
    )
    parser.add_argument(
        "--season",
        choices=sorted(SEASON_CONFIG.keys()),
        default=None,
        help="Optional forecast season override. Defaults to an automatic season based on today's date.",
    )
    args = parser.parse_args()

    pool_path = args.pool or Path(DEFAULT_POOL_PATH_TEMPLATE.format(year=args.year))
    run(args.year, pool_path, args.season)
