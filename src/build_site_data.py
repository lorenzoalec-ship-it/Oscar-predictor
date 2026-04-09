import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from train_model import (
    DEFAULT_BASELINE_NAME,
    DEFAULT_EXTENDED_VALIDATION_START,
    DEFAULT_MODERN_ERA_START,
    DEFAULT_TOP_PICK_CONFIDENCE_WEIGHT,
    FEATURES,
    MIN_TRAIN_YEARS,
    apply_top_pick_confidence_calibration,
    backtest_baseline_years,
    evaluate_latest_holdout,
    list_walk_forward_years,
    load_data,
    prepare_data,
    score_best_picture_year,
    summarize_top_pick_calibration,
    train_model_for_year,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
SITE_DATA_PATH = ROOT / "site" / "data" / "site_data.json"
SITE_DATA_JS_PATH = ROOT / "site" / "data" / "site_data.js"
FORECAST_HISTORY_DIR = OUTPUT_DIR / "history"
SITE_HISTORY_START_YEAR = 1999
FORECAST_SEASON_ORDER = ["early", "festival", "precursor", "post_nomination"]
FORECAST_SEASON_GUIDE = {
    "early": {
        "label": "Early",
        "summary": "The earliest board is meant to identify plausible contenders, not lock the winner. It should move a lot as real reviews, festivals, and awards data arrive.",
        "leans_on": "release timing, prestige profile, curated contender flags, early critic signal, and broad festival positioning",
        "best_for": "starting the field early and spotting which films belong on the board at all",
    },
    "festival": {
        "label": "Festival",
        "summary": "Once Venice, Telluride, TIFF, and fall launches start landing, the board should react more to real reception and premiere strength than to pure preseason priors.",
        "leans_on": "festival launches, critic scores, distributor strength, and early crowd response",
        "best_for": "sorting serious contenders from the larger preseason pool",
    },
    "precursor": {
        "label": "Precursor",
        "summary": "During guild and critics season, the forecast should behave more like an awards race and less like a release calendar watchlist.",
        "leans_on": "PGA, DGA, Critics Choice, BAFTA, SAG, Golden Globe signals, plus critics and nomination volume",
        "best_for": "tracking the real shape of the race before nominations lock",
    },
    "post_nomination": {
        "label": "Post Nomination",
        "summary": "After Oscar nominations, the board should be closest to a true winner model because the final field is known and precursor strength matters most.",
        "leans_on": "Oscar nominations, precursor wins, critic scores, and late-race package strength",
        "best_for": "final winner forecasting after the field is set",
    },
}


def find_latest_future_forecast():
    files = list_publishable_future_forecasts()
    if not files:
        raise FileNotFoundError("No future forecast CSVs found in output/.")

    latest_file = max(files, key=lambda path: int(path.stem.rsplit("_", 1)[-1]))
    year = int(latest_file.stem.rsplit("_", 1)[-1])
    return year, latest_file


def load_existing_site_data():
    if not SITE_DATA_PATH.exists():
        return {}


def count_future_forecast_signal_rows(df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    signal_rows = pd.Series(False, index=df.index)
    for column in [
        "manual_contender_flag",
        "metacritic_score",
        "tomatometer_rating",
        "festival_presence_score",
        "movie_vote_count",
    ]:
        if column in df.columns:
            signal_rows = signal_rows | pd.to_numeric(df[column], errors="coerce").fillna(0).gt(0)
    return int(signal_rows.sum())


def future_forecast_is_publishable(path: Path) -> bool:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return False

    if df.empty:
        return False

    return count_future_forecast_signal_rows(df) >= 5


def list_publishable_future_forecasts():
    files = sorted(OUTPUT_DIR.glob("future_best_picture_predictions_*.csv"))
    publishable = [path for path in files if future_forecast_is_publishable(path)]
    return publishable or files
    try:
        return json.loads(SITE_DATA_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def load_forecast_cards(path: Path, limit: int = 12):
    df = pd.read_csv(path).head(limit).copy()
    cards = []
    for idx, row in df.reset_index(drop=True).iterrows():
        cards.append(
            {
                "rank": idx + 1,
                "title": row.get("title"),
                "release_date": row.get("release_date"),
                "probability": float(row.get("best_picture_probability", 0)),
                "rating": float(row.get("movie_rating", 0)) if pd.notna(row.get("movie_rating")) else None,
                "vote_count": int(row.get("movie_vote_count", 0)) if pd.notna(row.get("movie_vote_count")) else 0,
                "genres": row.get("genres") or row.get("genre_ids") or "",
                "overview": row.get("overview") or row.get("description") or "",
                "poster_url": row.get("poster_url"),
                "forecast_season": row.get("forecast_season"),
                "prestige_score": float(row.get("prestige_score", 0)) if pd.notna(row.get("prestige_score")) else None,
                "manual_contender_flag": int(row.get("manual_contender_flag", 0)) if pd.notna(row.get("manual_contender_flag")) else 0,
            }
        )
    return cards


def forecast_season_for_df(df: pd.DataFrame):
    if "forecast_season" not in df.columns or df["forecast_season"].dropna().empty:
        return None
    return df["forecast_season"].dropna().iloc[0]


def forecast_season_index(season: Optional[str]) -> Optional[int]:
    if season not in FORECAST_SEASON_ORDER:
        return None
    return FORECAST_SEASON_ORDER.index(season)


def load_previous_forecast_cards(year: int, limit: int = 50):
    history_dir = FORECAST_HISTORY_DIR / str(year)
    if not history_dir.exists():
        return []

    history_files = sorted(history_dir.glob(f"future_best_picture_predictions_{year}_*.csv"))
    if not history_files:
        return []

    previous_df = pd.read_csv(history_files[-1]).head(limit).copy()
    cards = []
    for idx, row in previous_df.reset_index(drop=True).iterrows():
        cards.append(
            {
                "rank": idx + 1,
                "title": row.get("title"),
                "probability": float(row.get("best_picture_probability", 0)),
            }
        )
    return cards


def add_rank_changes(cards, previous_cards):
    previous_ranks = {card["title"]: card["rank"] for card in previous_cards}
    enriched = []
    for card in cards:
        previous_rank = previous_ranks.get(card["title"])
        if previous_rank is None:
            movement = "new"
            delta = None
        else:
            delta = previous_rank - card["rank"]
            if delta > 0:
                movement = "up"
            elif delta < 0:
                movement = "down"
            else:
                movement = "same"
        updated = dict(card)
        updated["previous_rank"] = previous_rank
        updated["rank_delta"] = delta
        updated["movement"] = movement
        enriched.append(updated)
    return enriched


def build_recent_race_cards(model_df, years, modern_era_start, baseline_rows=None, confidence_rows=None):
    baseline_map = {}
    if baseline_rows is not None and not baseline_rows.empty:
        baseline_map = {
            int(row["year_film"]): row
            for _, row in baseline_rows.iterrows()
        }
    confidence_map = {}
    if confidence_rows is not None and not confidence_rows.empty:
        confidence_map = {
            int(row["year_film"]): row
            for _, row in confidence_rows.iterrows()
        }

    cards = []
    for year in years:
        try:
            model, train_df = train_model_for_year(
                model_df,
                year,
                model_name="hgb",
                modern_era_start=modern_era_start,
            )
            results = score_best_picture_year(model, model_df, year)
        except ValueError:
            continue
        predicted = results.iloc[0]
        actual = results[results["best_picture_winner"] == 1].iloc[0]
        baseline_row = baseline_map.get(int(year))
        confidence_row = confidence_map.get(int(year))
        cards.append(
            {
                "year_film": int(year),
                "train_start": int(train_df["year_film"].min()),
                "train_end": int(train_df["year_film"].max()),
                "predicted_winner": predicted["film"],
                "predicted_probability": float(predicted["win_probability"]),
                "runner_up": results.iloc[1]["film"] if len(results) > 1 else None,
                "runner_up_probability": float(results.iloc[1]["win_probability"]) if len(results) > 1 else None,
                "leader_margin": float(predicted["leader_margin"]),
                "confidence_label": (
                    confidence_row["calibrated_confidence_label"]
                    if confidence_row is not None
                    else predicted["confidence_label"]
                ),
                "confidence_probability": (
                    float(confidence_row["calibrated_confidence"])
                    if confidence_row is not None
                    else float(predicted["win_probability"])
                ),
                "actual_winner": actual["film"],
                "correct": bool(predicted["film"] == actual["film"]),
                "baseline_predicted_winner": baseline_row["predicted_winner"] if baseline_row is not None else None,
                "baseline_correct": bool(baseline_row["correct"]) if baseline_row is not None else None,
                "top_three": [
                    {
                        "film": row["film"],
                        "probability": float(row["win_probability"]),
                    }
                    for _, row in results.head(3).iterrows()
                ],
            }
        )
    return cards


def build_actual_winners(model_df, start_year=2000):
    winners = model_df[
        (model_df["best_picture_nominee"] == 1)
        & (model_df["best_picture_winner"] == 1)
        & (model_df["year_film"] >= start_year)
    ][["year_film", "film"]].sort_values("year_film", ascending=False)

    return [
        {"year_film": int(row["year_film"]), "film": row["film"]}
        for _, row in winners.iterrows()
    ]


def build_historical_year_payload(model_df, years, confidence_rows=None):
    confidence_map = {}
    if confidence_rows is not None and not confidence_rows.empty:
        confidence_map = {
            int(row["year_film"]): row
            for _, row in confidence_rows.iterrows()
        }
    payload = []
    for year in years:
        try:
            model, train_df = train_model_for_year(
                model_df,
                year,
                model_name="hgb",
                modern_era_start=DEFAULT_EXTENDED_VALIDATION_START,
            )
            results = score_best_picture_year(model, model_df, year)
        except ValueError:
            continue
        summary = {
            "year_film": int(year),
            "train_start": int(train_df["year_film"].min()),
            "train_end": int(train_df["year_film"].max()),
            "top_pick_confidence": (
                float(confidence_map[int(year)]["calibrated_confidence"])
                if int(year) in confidence_map
                else None
            ),
            "top_pick_confidence_label": (
                confidence_map[int(year)]["calibrated_confidence_label"]
                if int(year) in confidence_map
                else None
            ),
            "rows": [],
        }
        for _, row in results.iterrows():
            summary["rows"].append(
                {
                    "rank": int(row["rank"]),
                    "film": row["film"],
                    "probability": float(row["win_probability"]),
                    "actual_winner": bool(row["best_picture_winner"]),
                    "oscar_nomination_count": int(row["oscar_nomination_count"]),
                    "tomatometer_rating": float(row["tomatometer_rating"]),
                    "momentum_score": float(row["momentum_score"]),
                    "margin_to_next": float(row["margin_to_next"]),
                    "confidence_label": (
                        confidence_map[int(year)]["calibrated_confidence_label"]
                        if int(year) in confidence_map
                        else row["confidence_label"]
                    ),
                    "confidence_probability": (
                        float(confidence_map[int(year)]["calibrated_confidence"])
                        if int(year) in confidence_map
                        else float(row["win_probability"])
                    ),
                }
            )
        payload.append(summary)
    return payload


def safe_backtest_years(model_df, modern_era_start, start_year=None):
    rows = []
    for year in list_walk_forward_years(
        model_df,
        modern_era_start=modern_era_start,
        start_year=start_year,
    ):
        try:
            model, train_df = train_model_for_year(
                model_df,
                int(year),
                model_name="hgb",
                modern_era_start=modern_era_start,
            )
            results = score_best_picture_year(model, model_df, int(year))
        except ValueError:
            continue

        predicted = results.iloc[0]
        actual_rows = results[results["best_picture_winner"] == 1]
        actual = actual_rows.iloc[0] if not actual_rows.empty else None
        rows.append(
            {
                "year_film": int(year),
                "train_start": int(train_df["year_film"].min()),
                "train_end": int(train_df["year_film"].max()),
                "predicted_winner": predicted["film"],
                "actual_winner": actual["film"] if actual is not None else None,
                "correct": bool(actual is not None and predicted["film"] == actual["film"]),
                "predicted_probability": float(predicted["win_probability"]),
                "runner_up": results.iloc[1]["film"] if len(results) > 1 else None,
                "runner_up_probability": float(results.iloc[1]["win_probability"]) if len(results) > 1 else None,
                "leader_margin": float(predicted["leader_margin"]),
                "confidence_label": predicted["confidence_label"],
            }
        )
    return pd.DataFrame(rows)


def build_future_year_payload():
    payload = []
    forecast_files = list_publishable_future_forecasts()
    for path in forecast_files:
        year = int(path.stem.rsplit("_", 1)[-1])
        df = pd.read_csv(path).copy()
        forecast_season = forecast_season_for_df(df)
        season_guide = FORECAST_SEASON_GUIDE.get(forecast_season, {})
        rows = []
        for _, row in df.head(20).iterrows():
            rows.append(
                {
                    "film": row.get("title"),
                    "probability": float(row.get("best_picture_probability", 0)),
                    "actual_winner": False,
                    "oscar_nomination_count": None,
                    "tomatometer_rating": None,
                    "momentum_score": None,
                    "poster_url": row.get("poster_url"),
                    "forecast_season": row.get("forecast_season"),
                    "prestige_score": float(row.get("prestige_score", 0)) if pd.notna(row.get("prestige_score")) else None,
                    "manual_contender_flag": int(row.get("manual_contender_flag", 0)) if pd.notna(row.get("manual_contender_flag")) else 0,
                }
            )

        payload.append(
            {
                "year_film": year,
                "train_start": None,
                "train_end": None,
                "is_future_forecast": True,
                "forecast_season": forecast_season,
                "forecast_mode_summary": season_guide.get("summary"),
                "forecast_mode_leans_on": season_guide.get("leans_on"),
                "forecast_mode_best_for": season_guide.get("best_for"),
                "rows": rows,
            }
        )
    return payload


def build_forecast_season_payload(current_forecast_year: int, current_forecast_season: Optional[str]):
    examples_by_season = {season: [] for season in FORECAST_SEASON_ORDER}

    for path in list_publishable_future_forecasts():
        year = int(path.stem.rsplit("_", 1)[-1])
        df = pd.read_csv(path).copy()
        season = forecast_season_for_df(df)
        if season not in examples_by_season:
            continue

        cards = load_forecast_cards(path, limit=5)
        if not cards:
            continue

        examples_by_season[season].append(
            {
                "year_film": year,
                "ceremony_year": year + 1,
                "top_pick": cards[0]["title"],
                "top_pick_probability": float(cards[0]["probability"]),
                "runner_up": cards[1]["title"] if len(cards) > 1 else None,
                "top_three": [
                    {
                        "title": card["title"],
                        "probability": float(card["probability"]),
                    }
                    for card in cards[:3]
                ],
                "is_current_forecast_year": year == current_forecast_year,
            }
        )

    payload = []
    current_index = forecast_season_index(current_forecast_season)
    for season in FORECAST_SEASON_ORDER:
        guide = FORECAST_SEASON_GUIDE[season]
        season_index = forecast_season_index(season)
        prior_examples = sorted(
            [item for item in examples_by_season[season] if not item["is_current_forecast_year"]],
            key=lambda item: item["year_film"],
            reverse=True,
        )
        current_example = next(
            (item for item in examples_by_season[season] if item["is_current_forecast_year"]),
            None,
        )
        if season == current_forecast_season:
            status = "live"
            status_label = "Live Now"
            status_summary = (
                f"The {current_forecast_year + 1} Oscars board is currently running in this mode."
            )
        elif current_index is not None and season_index is not None and season_index > current_index:
            status = "tbd"
            status_label = "TBD Later In The Season"
            status_summary = (
                f"This mode should only turn on once the race reaches {guide['label'].lower()} season."
            )
        else:
            status = "archive"
            status_label = "Archived Reference"
            status_summary = (
                "Use the archived examples below to see how this stage has behaved in prior races."
            )
        payload.append(
            {
                "slug": season,
                "label": guide["label"],
                "summary": guide["summary"],
                "leans_on": guide["leans_on"],
                "best_for": guide["best_for"],
                "status": status,
                "status_label": status_label,
                "status_summary": status_summary,
                "current_mode": season == current_forecast_season,
                "current_example": current_example,
                "prior_examples": prior_examples[:2],
            }
        )
    return payload


def build_payload():
    raw_df = load_data()
    model_df = prepare_data(raw_df)

    forecast_year, forecast_path = find_latest_future_forecast()
    forecast_cards = load_forecast_cards(forecast_path, limit=12)
    previous_forecast_cards = load_previous_forecast_cards(forecast_year, limit=50)
    forecast_cards = add_rank_changes(forecast_cards, previous_forecast_cards)
    hero = forecast_cards[0]

    holdout_result = evaluate_latest_holdout(
        model_df,
        model_name="hgb",
        verbose=False,
        modern_era_start=DEFAULT_MODERN_ERA_START,
    )
    if holdout_result is None:
        holdout_accuracy = 0.0
        holdout_summary = {
            "predicted_winner": "Unavailable",
            "actual_winner": "Unavailable",
            "year_film": None,
        }
    else:
        _, holdout_accuracy, holdout_summary = holdout_result

    production_backtest_df = safe_backtest_years(
        model_df,
        modern_era_start=DEFAULT_MODERN_ERA_START,
        start_year=SITE_HISTORY_START_YEAR,
    )
    production_backtest_df = apply_top_pick_confidence_calibration(production_backtest_df)
    production_backtest_accuracy = (
        float(production_backtest_df["correct"].mean()) if not production_backtest_df.empty else 0.0
    )

    extended_backtest_df = safe_backtest_years(
        model_df,
        modern_era_start=DEFAULT_EXTENDED_VALIDATION_START,
        start_year=DEFAULT_EXTENDED_VALIDATION_START + MIN_TRAIN_YEARS,
    )
    extended_backtest_df = apply_top_pick_confidence_calibration(extended_backtest_df)
    extended_backtest_accuracy = (
        float(extended_backtest_df["correct"].mean()) if not extended_backtest_df.empty else 0.0
    )
    raw_calibration_metrics = summarize_top_pick_calibration(
        extended_backtest_df,
        probability_col="predicted_probability",
    )
    calibrated_metrics = summarize_top_pick_calibration(
        extended_backtest_df,
        probability_col="calibrated_confidence",
    )
    extended_years = extended_backtest_df["year_film"].tolist() if not extended_backtest_df.empty else []
    baseline_backtest_df = backtest_baseline_years(
        model_df,
        years=extended_years,
        verbose=False,
        baseline_name=DEFAULT_BASELINE_NAME,
    )
    baseline_accuracy = float(baseline_backtest_df["correct"].mean()) if not baseline_backtest_df.empty else 0.0
    baseline_by_year = (
        baseline_backtest_df.set_index("year_film")
        if not baseline_backtest_df.empty
        else pd.DataFrame()
    )

    backtest_df = extended_backtest_df.copy()
    if not backtest_df.empty and not baseline_by_year.empty:
        backtest_df["baseline_predicted_winner"] = backtest_df["year_film"].map(
            baseline_by_year["predicted_winner"]
        )
        backtest_df["baseline_correct"] = backtest_df["year_film"].map(baseline_by_year["correct"]).fillna(False)
    else:
        backtest_df["baseline_predicted_winner"] = None
        backtest_df["baseline_correct"] = False
    backtest_rows = backtest_df.to_dict(orient="records")
    historical_years = build_historical_year_payload(
        model_df,
        sorted(backtest_df["year_film"].tolist()) if not backtest_df.empty else [],
        confidence_rows=extended_backtest_df,
    )
    recent_years = sorted(backtest_df["year_film"].tolist())[-10:] if not backtest_df.empty else []
    recent_races = build_recent_race_cards(
        model_df,
        recent_years,
        modern_era_start=DEFAULT_EXTENDED_VALIDATION_START,
        baseline_rows=baseline_backtest_df,
        confidence_rows=extended_backtest_df,
    )
    future_years = build_future_year_payload()
    season_modes = build_forecast_season_payload(
        current_forecast_year=forecast_year,
        current_forecast_season=hero.get("forecast_season"),
    )
    historical_only = [item for item in historical_years if not item.get("is_future_forecast")]
    all_years = historical_only + future_years
    all_years = sorted(all_years, key=lambda item: item["year_film"])
    holdout_confidence_row = None
    if (
        holdout_summary.get("year_film") is not None
        and not production_backtest_df.empty
        and int(holdout_summary["year_film"]) in production_backtest_df["year_film"].astype(int).tolist()
    ):
        holdout_confidence_row = production_backtest_df[
            production_backtest_df["year_film"] == int(holdout_summary["year_film"])
        ].iloc[0]

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": "hgb",
            "current_forecast_year": forecast_year,
            "current_ceremony_year": forecast_year + 1,
            "current_forecast_season": hero.get("forecast_season"),
        },
        "hero": hero,
        "forecast_cards": forecast_cards,
        "historical_years": all_years,
        "metrics": {
            "holdout_accuracy": holdout_accuracy,
            "holdout_predicted_winner": holdout_summary["predicted_winner"],
            "holdout_actual_winner": holdout_summary["actual_winner"],
            "holdout_year": holdout_summary["year_film"],
            "holdout_runner_up": holdout_summary.get("runner_up"),
            "holdout_leader_margin": holdout_summary.get("leader_margin", 0.0),
            "holdout_confidence_label": (
                holdout_confidence_row["calibrated_confidence_label"]
                if holdout_confidence_row is not None
                else holdout_summary.get("confidence_label", "low")
            ),
            "holdout_confidence_probability": (
                float(holdout_confidence_row["calibrated_confidence"])
                if holdout_confidence_row is not None
                else float(holdout_summary.get("predicted_probability", 0.0))
            ),
            "walk_forward_winner_accuracy": production_backtest_accuracy,
            "production_walk_forward_winner_accuracy": production_backtest_accuracy,
            "production_scored_years": int(len(production_backtest_df)),
            "production_first_scored_year": int(production_backtest_df["year_film"].min()) if not production_backtest_df.empty else None,
            "production_last_scored_year": int(production_backtest_df["year_film"].max()) if not production_backtest_df.empty else None,
            "production_training_start": DEFAULT_MODERN_ERA_START,
            "extended_walk_forward_winner_accuracy": extended_backtest_accuracy,
            "extended_scored_years": int(len(extended_backtest_df)),
            "extended_first_scored_year": int(extended_backtest_df["year_film"].min()) if not extended_backtest_df.empty else None,
            "extended_last_scored_year": int(extended_backtest_df["year_film"].max()) if not extended_backtest_df.empty else None,
            "extended_training_start": DEFAULT_EXTENDED_VALIDATION_START,
            "baseline_accuracy": baseline_accuracy,
            "baseline_name": DEFAULT_BASELINE_NAME,
            "baseline_scored_years": int(len(baseline_backtest_df)),
            "confidence_weight": DEFAULT_TOP_PICK_CONFIDENCE_WEIGHT,
            "extended_top_pick_brier_raw": raw_calibration_metrics["brier"],
            "extended_top_pick_brier_calibrated": calibrated_metrics["brier"],
            "extended_top_pick_log_loss_raw": raw_calibration_metrics["log_loss"],
            "extended_top_pick_log_loss_calibrated": calibrated_metrics["log_loss"],
            "feature_count": len(FEATURES),
            "last_generated_at": datetime.now(timezone.utc).isoformat(),
            "current_forecast_season": hero.get("forecast_season"),
        },
        "recent_races": recent_races,
        "season_modes": season_modes,
        "actual_winners": build_actual_winners(model_df, start_year=SITE_HISTORY_START_YEAR),
        "backtest_rows": backtest_rows,
        "methodology": {
            "headline": "The site uses a production Best Picture model trained on modern-era nominees, plus a longer walk-forward validation window to keep the headline honest.",
            "bullets": [
                f"Walk-forward means each historical film year is scored only with models trained on earlier film years. The live production setup starts training at {DEFAULT_MODERN_ERA_START} and currently scores {production_backtest_df['year_film'].min() if not production_backtest_df.empty else 'recent'}-{production_backtest_df['year_film'].max() if not production_backtest_df.empty else 'recent'}.",
                f"The longer validation view starts training at {DEFAULT_EXTENDED_VALIDATION_START} so we can review a tougher {len(extended_backtest_df)}-year window from {extended_backtest_df['year_film'].min() if not extended_backtest_df.empty else 'recent'}-{extended_backtest_df['year_film'].max() if not extended_backtest_df.empty else 'recent'}.",
                "The winner model is trained on Oscar nomination totals, precursor wins and nominations from PGA, DGA, Critics Choice, BAFTA, SAG, and the Golden Globes, plus critics scores, release timing, distributor flags, genre tags, festivals, and director history.",
                f"The simple comparison baseline picks the film with the most precursor wins, then precursor nominations, then Oscar nominations, Metacritic, and Rotten Tomatoes. That baseline is shown alongside the model on the longer validation window.",
                f"Confidence labels are now shrinkage-calibrated toward prior walk-forward accuracy. On the 2015-2024 extended window, top-pick Brier improved from {raw_calibration_metrics['brier']:.3f} to {calibrated_metrics['brier']:.3f}.",
                "Future races rely on TMDb-first movie pool data and a season-aware blend that shifts weight from broad prestige tracking early in the year toward awards-style signals later in the race.",
            ],
        },
    }
    return payload


def run():
    payload = build_payload()
    SITE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA_PATH.write_text(json.dumps(payload, indent=2))
    SITE_DATA_JS_PATH.write_text(f"window.__SITE_DATA__ = {json.dumps(payload)};")
    print(f"Wrote site data to {SITE_DATA_PATH}")


if __name__ == "__main__":
    run()
