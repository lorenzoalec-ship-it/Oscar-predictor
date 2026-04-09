import argparse
import math

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, classification_report, log_loss


DATA_PATH = "output/model_data.csv"
MIN_TRAIN_YEARS = 10
DEFAULT_MODERN_ERA_START = 2010
DEFAULT_EXTENDED_VALIDATION_START = 2005
DEFAULT_BASELINE_NAME = "Precursor Wins Baseline"
DEFAULT_TOP_PICK_CONFIDENCE_WEIGHT = 0.7

NOMINEE_FEATURES = [
    "release_month",
    "tomatometer_rating",
    "metacritic_score",
    "movie_rating",
    "movie_vote_count_log",
    "director_prior_directing_nominations",
    "director_prior_directing_wins",
    "director_has_prior_directing_win",
    "is_streaming_distributor",
    "is_prestige_distributor",
    "is_major_studio_distributor",
    "is_drama_genre",
    "is_history_genre",
    "is_biography_genre",
    "is_war_genre",
    "is_music_genre",
    "is_romance_genre",
    "prestige_genre_score",
    "cannes_flag",
    "venice_flag",
    "tiff_flag",
    "telluride_flag",
    "sundance_flag",
    "sxsw_flag",
    "festival_presence_score",
    "major_festival_flag",
]

# Keep winner features focused on outcome-level signals instead of
# re-feeding raw precursor nomination volume, which overfit the repaired data.
WINNER_FEATURES = [
    "tomatometer_rating",
    "metacritic_score",
    "oscar_nomination_count",
    "golden_globe_win",
    "sag_win",
    "bafta_win",
    "pga_win",
    "dga_win",
    "critics_choice_win",
    "release_month",
    "high_nomination_flag",
    "movie_rating",
    "movie_vote_count_log",
    "director_prior_directing_nominations",
    "director_prior_directing_wins",
    "director_has_prior_directing_win",
    "is_streaming_distributor",
    "is_prestige_distributor",
    "is_major_studio_distributor",
    "is_drama_genre",
    "is_history_genre",
    "is_biography_genre",
    "is_war_genre",
    "is_music_genre",
    "is_romance_genre",
    "prestige_genre_score",
    "cannes_flag",
    "venice_flag",
    "tiff_flag",
    "telluride_flag",
    "sundance_flag",
    "sxsw_flag",
    "festival_presence_score",
    "major_festival_flag",
    "nominee_probability",
]

FEATURES = WINNER_FEATURES


def load_data():
    return pd.read_csv(DATA_PATH)


def prepare_data(df):
    model_df = df.copy()
    model_df = model_df.dropna(subset=["release_month"]).copy()
    model_df["movie_vote_count"] = pd.to_numeric(
        model_df.get("movie_vote_count"), errors="coerce"
    ).fillna(0)
    model_df["movie_vote_count_log"] = model_df["movie_vote_count"].apply(
        lambda value: math.log1p(value) if value >= 0 else 0
    )

    numeric_cols = list(set(NOMINEE_FEATURES + WINNER_FEATURES + ["best_picture_winner", "best_picture_nominee", "year_film"]))
    for col in numeric_cols:
        if col in model_df.columns:
            model_df[col] = pd.to_numeric(model_df[col], errors="coerce")

    fill_zero_cols = [
        "tomatometer_rating",
        "metacritic_score",
        "golden_globe_win",
        "sag_win",
        "bafta_win",
        "pga_win",
        "dga_win",
        "critics_choice_win",
        "globe_nom_count",
        "sag_nom_count",
        "bafta_nom_count",
        "pga_nom_count",
        "dga_nom_count",
        "critics_choice_nom_count",
        "high_nomination_flag",
        "movie_rating",
        "movie_vote_count_log",
        "director_prior_directing_nominations",
        "director_prior_directing_wins",
        "director_has_prior_directing_win",
        "is_streaming_distributor",
        "is_prestige_distributor",
        "is_major_studio_distributor",
        "is_drama_genre",
        "is_history_genre",
        "is_biography_genre",
        "is_war_genre",
        "is_music_genre",
        "is_romance_genre",
        "prestige_genre_score",
        "cannes_flag",
        "venice_flag",
        "tiff_flag",
        "telluride_flag",
        "sundance_flag",
        "sxsw_flag",
        "festival_presence_score",
        "major_festival_flag",
    ]
    for col in fill_zero_cols:
        model_df[col] = model_df[col].fillna(0)

    model_df = model_df.dropna(subset=["year_film", "best_picture_winner", "best_picture_nominee"]).copy()
    model_df["year_film"] = model_df["year_film"].astype(int)
    model_df["best_picture_winner"] = model_df["best_picture_winner"].astype(int)
    model_df["best_picture_nominee"] = model_df["best_picture_nominee"].astype(int)
    return model_df


def filter_training_window(df, modern_era_start=None):
    if modern_era_start is None:
        return df
    return df[df["year_film"] >= int(modern_era_start)].copy()


def build_model(model_name):
    if model_name == "rf":
        return RandomForestClassifier(
            n_estimators=300,
            random_state=42,
            class_weight="balanced",
            min_samples_leaf=2,
        )
    if model_name == "hgb":
        return HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=300,
            max_leaf_nodes=15,
            min_samples_leaf=5,
            l2_regularization=0.1,
            random_state=42,
            class_weight="balanced",
        )
    raise ValueError(f"Unsupported model: {model_name}")


def predict_positive_proba(model, X):
    probs = model.predict_proba(X)
    if probs.ndim == 1:
        return probs
    positive_index = list(model.classes_).index(1)
    return probs[:, positive_index]


def confidence_label_from_gap(gap: float) -> str:
    if gap >= 0.35:
        return "very_high"
    if gap >= 0.2:
        return "high"
    if gap >= 0.1:
        return "medium"
    return "low"


def confidence_label_from_probability(probability: float) -> str:
    if probability >= 0.75:
        return "very_high"
    if probability >= 0.6:
        return "high"
    if probability >= 0.45:
        return "medium"
    return "low"


def calibrate_top_pick_confidence(
    raw_probability: float,
    prior_accuracy: float,
    weight: float = DEFAULT_TOP_PICK_CONFIDENCE_WEIGHT,
) -> float:
    raw_probability = min(max(float(raw_probability), 0.0), 1.0)
    prior_accuracy = min(max(float(prior_accuracy), 0.0), 1.0)
    blended = weight * raw_probability + (1 - weight) * prior_accuracy
    # Confidence tuning should only shrink overconfident calls, not raise them.
    return min(raw_probability, blended)


def apply_top_pick_confidence_calibration(
    summary_df: pd.DataFrame,
    probability_col: str = "predicted_probability",
    correct_col: str = "correct",
    weight: float = DEFAULT_TOP_PICK_CONFIDENCE_WEIGHT,
) -> pd.DataFrame:
    if summary_df.empty:
        calibrated = summary_df.copy()
        calibrated["prior_walk_forward_accuracy"] = []
        calibrated["calibrated_confidence"] = []
        calibrated["calibrated_confidence_label"] = []
        return calibrated

    calibrated = summary_df.sort_values("year_film").reset_index(drop=True).copy()
    prior_accuracies = []
    confidence_values = []
    confidence_labels = []

    for idx, row in calibrated.iterrows():
        if idx == 0:
            prior_accuracy = float(row[probability_col])
        else:
            prior_accuracy = float(calibrated.loc[: idx - 1, correct_col].astype(int).mean())
        calibrated_confidence = calibrate_top_pick_confidence(
            raw_probability=float(row[probability_col]),
            prior_accuracy=prior_accuracy,
            weight=weight,
        )
        prior_accuracies.append(prior_accuracy)
        confidence_values.append(calibrated_confidence)
        confidence_labels.append(confidence_label_from_probability(calibrated_confidence))

    calibrated["prior_walk_forward_accuracy"] = prior_accuracies
    calibrated["calibrated_confidence"] = confidence_values
    calibrated["calibrated_confidence_label"] = confidence_labels
    return calibrated


def summarize_top_pick_calibration(
    summary_df: pd.DataFrame,
    probability_col: str = "predicted_probability",
    correct_col: str = "correct",
) -> dict:
    if summary_df.empty:
        return {"brier": 0.0, "log_loss": 0.0}

    y_true = summary_df[correct_col].astype(int)
    y_prob = pd.to_numeric(summary_df[probability_col], errors="coerce").fillna(0).clip(1e-6, 1 - 1e-6)
    return {
        "brier": float(brier_score_loss(y_true, y_prob)),
        "log_loss": float(log_loss(y_true, y_prob, labels=[0, 1])),
    }


def add_confidence_diagnostics(results: pd.DataFrame, probability_col: str) -> pd.DataFrame:
    if results.empty:
        return results

    diagnosed = results.sort_values(probability_col, ascending=False).reset_index(drop=True).copy()
    diagnosed["rank"] = diagnosed.index + 1
    diagnosed["margin_to_next"] = 0.0
    if len(diagnosed) > 1:
        diagnosed.iloc[:-1, diagnosed.columns.get_loc("margin_to_next")] = (
            diagnosed.iloc[:-1][probability_col].to_numpy() - diagnosed.iloc[1:][probability_col].to_numpy()
        )
        leader_gap = float(diagnosed.loc[0, probability_col] - diagnosed.loc[1, probability_col])
    else:
        leader_gap = float(diagnosed.loc[0, probability_col])
    diagnosed["leader_margin"] = leader_gap
    diagnosed["confidence_label"] = confidence_label_from_gap(leader_gap)
    return diagnosed


def score_precursor_baseline(results: pd.DataFrame) -> pd.DataFrame:
    baseline = results.copy()
    win_cols = [
        "pga_win",
        "dga_win",
        "bafta_win",
        "sag_win",
        "golden_globe_win",
        "critics_choice_win",
    ]
    nom_cols = [
        "pga_nom_count",
        "dga_nom_count",
        "bafta_nom_count",
        "sag_nom_count",
        "globe_nom_count",
        "critics_choice_nom_count",
    ]
    for col in win_cols + nom_cols + ["oscar_nomination_count", "metacritic_score", "tomatometer_rating"]:
        baseline[col] = pd.to_numeric(baseline.get(col), errors="coerce").fillna(0)

    baseline["baseline_precursor_wins"] = baseline[win_cols].sum(axis=1)
    baseline["baseline_precursor_nominations"] = baseline[nom_cols].sum(axis=1)
    baseline = baseline.sort_values(
        [
            "baseline_precursor_wins",
            "baseline_precursor_nominations",
            "oscar_nomination_count",
            "metacritic_score",
            "tomatometer_rating",
        ],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)
    return baseline


def train_model(train_df, model_name="hgb"):
    nominee_model = build_model(model_name)
    nominee_model.fit(train_df[NOMINEE_FEATURES], train_df["best_picture_nominee"])

    winner_train = train_df[train_df["best_picture_nominee"] == 1].copy()
    winner_train["nominee_probability"] = predict_positive_proba(
        nominee_model,
        winner_train[NOMINEE_FEATURES],
    )

    winner_model = build_model(model_name)
    winner_model.fit(winner_train[WINNER_FEATURES], winner_train["best_picture_winner"])
    return {
        "nominee_model": nominee_model,
        "winner_model": winner_model,
    }


def score_best_picture_year(model, df, year):
    results = df[df["year_film"] == year].copy()
    results = results[results["best_picture_nominee"] == 1].copy()

    if results.empty:
        available_years = sorted(df.loc[df["best_picture_nominee"] == 1, "year_film"].dropna().unique())
        if available_years:
            raise ValueError(
                f"No Best Picture nominees found for {year}. "
                f"Available years: {int(available_years[0])} to {int(available_years[-1])}."
            )
        raise ValueError(f"No Best Picture nominees found for {year}.")

    results["nominee_probability"] = predict_positive_proba(
        model["nominee_model"],
        results[NOMINEE_FEATURES],
    )
    probs = predict_positive_proba(model["winner_model"], results[WINNER_FEATURES])
    results["win_probability"] = probs
    total = results["win_probability"].sum()
    if total > 0:
        results["win_probability"] = results["win_probability"] / total

    return add_confidence_diagnostics(results, "win_probability")


def print_year_results(results, year, train_year_min, train_year_max):
    actual_winner_row = results[results["best_picture_winner"] == 1].head(1)
    predicted_winner_row = results.head(1)

    actual_winner = actual_winner_row.iloc[0]["film"] if not actual_winner_row.empty else "Unknown"
    predicted_winner = predicted_winner_row.iloc[0]["film"] if not predicted_winner_row.empty else "Unknown"
    is_correct = actual_winner == predicted_winner

    print(
        f"\nBest Picture race for {year} "
        f"(trained on {train_year_min}-{train_year_max}):"
    )
    print(
        results[
            [
                "film",
                "win_probability",
                "best_picture_winner",
                "oscar_nomination_count",
                "tomatometer_rating",
                "momentum_score",
            ]
        ].to_string(index=False)
    )
    print(f"\nPredicted winner: {predicted_winner}")
    print(f"Actual winner: {actual_winner}")
    print(f"Model picked correctly: {'yes' if is_correct else 'no'}")


def build_year_summary(results, year, train_year_min, train_year_max):
    actual_winner_row = results[results["best_picture_winner"] == 1].head(1)
    predicted_winner_row = results.head(1)
    runner_up_row = results.iloc[[1]] if len(results) > 1 else pd.DataFrame()

    actual_winner = actual_winner_row.iloc[0]["film"] if not actual_winner_row.empty else "Unknown"
    predicted_winner = predicted_winner_row.iloc[0]["film"] if not predicted_winner_row.empty else "Unknown"
    predicted_probability = (
        float(predicted_winner_row.iloc[0]["win_probability"]) if not predicted_winner_row.empty else 0.0
    )
    runner_up = runner_up_row.iloc[0]["film"] if not runner_up_row.empty else None
    leader_margin = (
        float(predicted_winner_row.iloc[0]["leader_margin"]) if not predicted_winner_row.empty else 0.0
    )
    confidence_label = (
        predicted_winner_row.iloc[0]["confidence_label"] if not predicted_winner_row.empty else "low"
    )

    return {
        "year_film": int(year),
        "train_start": int(train_year_min),
        "train_end": int(train_year_max),
        "predicted_winner": predicted_winner,
        "actual_winner": actual_winner,
        "correct": predicted_winner == actual_winner,
        "predicted_probability": predicted_probability,
        "runner_up": runner_up,
        "leader_margin": leader_margin,
        "confidence_label": confidence_label,
    }


def show_feature_importance(model, feature_names):
    if not hasattr(model, "feature_importances_"):
        print("\nFeature importance: not available for this model.")
        return

    importance_df = pd.DataFrame(
        {"feature": feature_names, "importance": model.feature_importances_}
    ).sort_values("importance", ascending=False)
    print("\nFeature importance:")
    print(importance_df.to_string(index=False))


def evaluate_latest_holdout(df, model_name="hgb", verbose=True, modern_era_start=None):
    years = sorted(df["year_film"].unique())
    if len(years) <= MIN_TRAIN_YEARS:
        print("\nNot enough yearly history for a holdout evaluation.")
        return None

    holdout_year = years[-1]
    train_df = filter_training_window(df[df["year_film"] < holdout_year].copy(), modern_era_start)
    test_df = df[(df["year_film"] == holdout_year) & (df["best_picture_nominee"] == 1)].copy()

    if train_df["best_picture_nominee"].sum() == 0:
        print("\nNo nominee positives in the selected training window.")
        return None
    if train_df.loc[train_df["best_picture_nominee"] == 1, "best_picture_winner"].nunique() < 2:
        print("\nNot enough winner variation in the selected training window.")
        return None

    model = train_model(train_df, model_name=model_name)
    test_df["nominee_probability"] = predict_positive_proba(
        model["nominee_model"],
        test_df[NOMINEE_FEATURES],
    )
    preds = model["winner_model"].predict(test_df[WINNER_FEATURES])
    y_test = test_df["best_picture_winner"]
    acc = accuracy_score(y_test, preds)
    holdout_results = score_best_picture_year(model, df, holdout_year)
    holdout_summary = build_year_summary(
        holdout_results,
        holdout_year,
        int(train_df["year_film"].min()),
        int(train_df["year_film"].max()),
    )

    if verbose:
        print(
            f"\nLatest-year holdout evaluation ({model_name}): "
            f"train={train_df['year_film'].min()}-{train_df['year_film'].max()}, "
            f"test={holdout_year}"
        )
        print(f"Holdout accuracy: {acc:.2f}")
        print(
            "Holdout winner summary: "
            f"predicted={holdout_summary['predicted_winner']}, "
            f"actual={holdout_summary['actual_winner']}, "
            f"correct={'yes' if holdout_summary['correct'] else 'no'}"
        )
        print("\nClassification report:")
        print(classification_report(y_test, preds, zero_division=0))
        show_feature_importance(model["winner_model"], WINNER_FEATURES)
    return model, acc, holdout_summary


def train_model_for_year(df, year, model_name="hgb", modern_era_start=None):
    train_df = filter_training_window(df[df["year_film"] < year].copy(), modern_era_start)
    train_years = sorted(train_df["year_film"].unique())

    if len(train_years) < MIN_TRAIN_YEARS:
        if train_years:
            raise ValueError(
                f"Not enough prior years to score {year}. "
                f"Found {len(train_years)} training years ({train_years[0]}-{train_years[-1]}), "
                f"need at least {MIN_TRAIN_YEARS}."
            )
        raise ValueError(f"No prior training data available to score {year}.")
    if train_df["best_picture_nominee"].sum() == 0:
        raise ValueError(f"No nominee positives available in the training window to score {year}.")
    if train_df.loc[train_df["best_picture_nominee"] == 1, "best_picture_winner"].nunique() < 2:
        raise ValueError(f"Not enough winner variation in the training window to score {year}.")

    model = train_model(train_df, model_name=model_name)
    return model, train_df


def list_walk_forward_years(df, modern_era_start=None, start_year=None):
    years = sorted(int(year) for year in df["year_film"].dropna().unique())
    eligible_years = []

    for year in years:
        if start_year is not None and int(year) < int(start_year):
            continue

        prior_years = sorted(df.loc[df["year_film"] < year, "year_film"].unique())
        if len(prior_years) < MIN_TRAIN_YEARS:
            continue

        try:
            train_model_for_year(df, year, model_name="hgb", modern_era_start=modern_era_start)
        except ValueError:
            continue
        eligible_years.append(int(year))

    return eligible_years


def backtest_years(df, model_name="hgb", verbose=True, modern_era_start=None, years=None):
    years = sorted(df["year_film"].unique())
    rows = []

    if years is not None:
        years = sorted(int(year) for year in years)

    for year in years:
        prior_years = sorted(df.loc[df["year_film"] < year, "year_film"].unique())
        if len(prior_years) < MIN_TRAIN_YEARS:
            continue

        try:
            model, train_df = train_model_for_year(
                df,
                year,
                model_name=model_name,
                modern_era_start=modern_era_start,
            )
        except ValueError:
            continue
        results = score_best_picture_year(model, df, int(year))
        predicted_winner = results.iloc[0]["film"]
        actual_rows = results[results["best_picture_winner"] == 1]
        actual_winner = actual_rows.iloc[0]["film"] if not actual_rows.empty else None

        rows.append(
            {
                "year_film": int(year),
                "train_start": int(train_df["year_film"].min()),
                "train_end": int(train_df["year_film"].max()),
                "predicted_winner": predicted_winner,
                "actual_winner": actual_winner,
                "correct": predicted_winner == actual_winner,
                "predicted_probability": float(results.iloc[0]["win_probability"]),
                "runner_up": results.iloc[1]["film"] if len(results) > 1 else None,
                "runner_up_probability": float(results.iloc[1]["win_probability"]) if len(results) > 1 else None,
                "leader_margin": float(results.iloc[0]["leader_margin"]),
                "confidence_label": results.iloc[0]["confidence_label"],
            }
        )

    summary = pd.DataFrame(rows)
    accuracy = summary["correct"].mean() if not summary.empty else 0

    if verbose:
        print(f"\nWalk-forward Best Picture backtest ({model_name}):")
        print(summary.to_string(index=False))
        print(f"\nYear-level winner accuracy: {accuracy:.2%}")
    return summary


def backtest_baseline_years(df, years=None, verbose=True, baseline_name=DEFAULT_BASELINE_NAME):
    if years is None:
        years = sorted(int(year) for year in df["year_film"].dropna().unique())
    else:
        years = sorted(int(year) for year in years)

    rows = []
    for year in years:
        results = df[(df["year_film"] == int(year)) & (df["best_picture_nominee"] == 1)].copy()
        if results.empty:
            continue

        ranked = score_precursor_baseline(results)
        predicted_winner = ranked.iloc[0]["film"]
        actual_rows = ranked[ranked["best_picture_winner"] == 1]
        actual_winner = actual_rows.iloc[0]["film"] if not actual_rows.empty else None
        runner_up = ranked.iloc[1]["film"] if len(ranked) > 1 else None

        rows.append(
            {
                "year_film": int(year),
                "predicted_winner": predicted_winner,
                "actual_winner": actual_winner,
                "correct": predicted_winner == actual_winner,
                "runner_up": runner_up,
                "baseline_name": baseline_name,
                "precursor_wins": int(ranked.iloc[0]["baseline_precursor_wins"]),
                "precursor_nominations": int(ranked.iloc[0]["baseline_precursor_nominations"]),
            }
        )

    summary = pd.DataFrame(rows)
    accuracy = summary["correct"].mean() if not summary.empty else 0.0

    if verbose:
        print(f"\n{baseline_name}:")
        print(summary.to_string(index=False))
        print(f"\nYear-level winner accuracy: {accuracy:.2%}")
    return summary


def compare_models(df, modern_era_start=None):
    summaries = []
    for model_name in ["rf", "hgb"]:
        holdout = evaluate_latest_holdout(df, model_name=model_name, modern_era_start=modern_era_start)
        if holdout is None:
            continue
        _, holdout_acc, holdout_summary = holdout
        summary = backtest_years(df, model_name=model_name, modern_era_start=modern_era_start)
        winner_acc = summary["correct"].mean() if not summary.empty else 0
        summaries.append(
            {
                "model": model_name,
                "holdout_accuracy": holdout_acc,
                "holdout_predicted_winner": holdout_summary["predicted_winner"],
                "holdout_actual_winner": holdout_summary["actual_winner"],
                "walk_forward_winner_accuracy": winner_acc,
            }
        )

    comparison = pd.DataFrame(summaries).sort_values(
        ["walk_forward_winner_accuracy", "holdout_accuracy"],
        ascending=False,
    )
    print("\nModel comparison:")
    print(comparison.to_string(index=False))
    return comparison


def run(year=None, backtest=False, model_name="hgb", compare=False, modern_era_start=DEFAULT_MODERN_ERA_START):
    print("Loading data...")
    df = load_data()

    print("Preparing data...")
    model_df = prepare_data(df)

    if compare:
        return compare_models(model_df, modern_era_start=modern_era_start)

    print("Evaluating latest holdout year...")
    evaluate_latest_holdout(model_df, model_name=model_name, modern_era_start=modern_era_start)

    if backtest:
        backtest_years(model_df, model_name=model_name, modern_era_start=modern_era_start)

    if year is not None:
        print(f"\nScoring Best Picture race for {year}...")
        model, train_df = train_model_for_year(
            model_df,
            year,
            model_name=model_name,
            modern_era_start=modern_era_start,
        )
        results = score_best_picture_year(model, model_df, year)
        print_year_results(
            results,
            year,
            int(train_df["year_film"].min()),
            int(train_df["year_film"].max()),
        )
        return results

    return model_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train a Best Picture model with walk-forward evaluation and score historical races."
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Historical film year to score, for example 2023 for the 2024 Oscars.",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run a walk-forward Best Picture backtest.",
    )
    parser.add_argument(
        "--model",
        choices=["rf", "hgb"],
        default="hgb",
        help="Model to use: histogram gradient boosting (`hgb`, default) or random forest (`rf`).",
    )
    parser.add_argument(
        "--compare-models",
        action="store_true",
        help="Compare random forest and gradient boosting on the same walk-forward setup.",
    )
    parser.add_argument(
        "--modern-era-start",
        type=int,
        default=DEFAULT_MODERN_ERA_START,
        help="First film year to include in each training window. Defaults to 2010.",
    )
    args = parser.parse_args()

    run(
        year=args.year,
        backtest=args.backtest,
        model_name=args.model,
        compare=args.compare_models,
        modern_era_start=args.modern_era_start,
    )
