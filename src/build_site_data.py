import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from train_category_model import (
    CATEGORY_CONFIG,
    backtest_category,
)
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


def build_oscar_acting_lookup(oscar_category: str = "ACTOR IN A LEADING ROLE") -> dict:
    """
    Returns {normalized_name: {"nominations": N, "wins": W}}
    for the given Oscar category (e.g. ACTOR IN A LEADING ROLE, ACTRESS IN A LEADING ROLE, DIRECTING).
    """
    try:
        df = pd.read_csv(ROOT / "data" / "raw" / "the_oscar_award.csv")
        filtered = df[df["category"].str.upper().str.contains(oscar_category.upper(), na=False)]
        lookup = {}
        for name, grp in filtered.groupby("name"):
            key = " ".join(str(name).upper().split())
            lookup[key] = {
                "nominations": int(len(grp)),
                "wins": int(grp["winner"].sum()),
            }
        return lookup
    except Exception:
        return {}
OUTPUT_DIR = ROOT / "output"
SITE_DATA_PATH = ROOT / "site" / "data" / "site_data.json"
SITE_DATA_JS_PATH = ROOT / "site" / "data" / "site_data.js"
FORECAST_HISTORY_DIR = OUTPUT_DIR / "history"
SITE_HISTORY_START_YEAR = 1999
CURRENT_FORECAST_YEAR = 2026  # Only this year appears as a live future forecast in the dropdown
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


def _safe_int_col(row, col):
    v = row.get(col)
    try:
        return int(float(v)) if v is not None and str(v) != "nan" else 0
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Festival Watch configuration
# ---------------------------------------------------------------------------

# Dates are approximate and updated annually. Status (upcoming/active/completed)
# is computed at build time against the current date.
FESTIVAL_CONFIG = {
    2026: [
        {"key": "sundance",  "name": "Sundance Film Festival",            "flag": "sundance_flag", "start": "2026-01-22", "end": "2026-02-01", "location": "Park City, UT",    "oscar_note": "Breakout indie contenders"},
        {"key": "berlin",    "name": "Berlin International Film Festival","flag": "berlin_flag",   "start": "2026-02-13", "end": "2026-02-23", "location": "Berlin, Germany",   "oscar_note": "International & art-house pipeline"},
        {"key": "sxsw",     "name": "SXSW Film Festival",                "flag": "sxsw_flag",     "start": "2026-03-13", "end": "2026-03-21", "location": "Austin, TX",        "oscar_note": "Emerging US filmmakers"},
        {"key": "cannes",    "name": "Cannes Film Festival",              "flag": "cannes_flag",   "start": "2026-05-13", "end": "2026-05-24", "location": "Cannes, France",    "oscar_note": "Palme d'Or winners often contend"},
        {"key": "venice",    "name": "Venice Film Festival",              "flag": "venice_flag",   "start": "2026-08-26", "end": "2026-09-05", "location": "Venice, Italy",     "oscar_note": "Strong Oscar track record"},
        {"key": "telluride", "name": "Telluride Film Festival",           "flag": "telluride_flag","start": "2026-08-28", "end": "2026-09-01", "location": "Telluride, CO",     "oscar_note": "First look at fall frontrunners"},
        {"key": "tiff",      "name": "Toronto International Film Festival","flag": "tiff_flag",    "start": "2026-09-10", "end": "2026-09-20", "location": "Toronto, Canada",   "oscar_note": "Audience Award a BP bellwether"},
        {"key": "nyff",      "name": "New York Film Festival",            "flag": "nyff_flag",     "start": "2026-09-25", "end": "2026-10-11", "location": "New York, NY",      "oscar_note": "Prestige art-house showcase"},
        {"key": "afi",       "name": "AFI Fest",                          "flag": "afi_flag",      "start": "2026-10-15", "end": "2026-10-19", "location": "Los Angeles, CA",   "oscar_note": "Studio awards plays premiere here"},
    ],
}


def build_festival_watch_payload(year: int) -> list[dict]:
    """
    Build the festival watch payload for the given eligibility year.
    Each festival entry includes:
      - Status: upcoming / active / completed
      - confirmed_films: films flagged as attending this festival (from manual_festival_flags.csv)
      - on_our_radar: top-10 BP contenders not yet confirmed at any major festival
    """
    from datetime import date

    festivals = FESTIVAL_CONFIG.get(year, [])
    if not festivals:
        return []

    today = date.today()

    # Load BP predictions for Oscar probability and film metadata
    bp_path = OUTPUT_DIR / f"future_best_picture_predictions_{year}.csv"
    if not bp_path.exists():
        return []
    bp_df = pd.read_csv(bp_path)

    # Load confirmed festival flags
    flags_path = ROOT / "data" / "raw" / "manual_festival_flags.csv"
    flags_df = pd.read_csv(flags_path) if flags_path.exists() else pd.DataFrame()
    if not flags_df.empty:
        flags_df = flags_df[flags_df["year_film"] == year].copy()

    # Build a lookup: title → BP row (probability + metadata)
    bp_lookup = {}
    for _, row in bp_df.iterrows():
        bp_lookup[str(row["title"]).strip().lower()] = row

    def _buzz_score(bp_row):
        """Composite buzz score: BP probability (primary) + critical reception signals."""
        if bp_row is None:
            return 0.0
        prob = float(bp_row.get("best_picture_probability", 0) or 0)
        rt = float(bp_row.get("tomatometer_rating", 0) or 0) / 100
        mc = float(bp_row.get("metacritic_score", 0) or 0) / 100
        return prob * 0.60 + rt * 0.25 + mc * 0.15

    def _film_card(title, bp_row=None):
        if bp_row is None:
            bp_row = bp_lookup.get(str(title).strip().lower(), {})
        prob = float(bp_row.get("best_picture_probability", 0)) if hasattr(bp_row, "get") else 0
        rt = float(bp_row.get("tomatometer_rating", 0) or 0) if hasattr(bp_row, "get") else 0
        mc = float(bp_row.get("metacritic_score", 0) or 0) if hasattr(bp_row, "get") else 0
        # A film is pre-release if it has the flag set, or if it has no RT/MC/votes yet
        pre_rel_flag = int(bp_row.get("pre_release", 0) or 0) if hasattr(bp_row, "get") else 0
        votes = float(bp_row.get("no_of_persons_voted", 0) or 0) if hasattr(bp_row, "get") else 0
        is_pre_release = bool(pre_rel_flag or (rt == 0 and mc == 0 and votes < 10))
        return {
            "title": title,
            "probability": round(prob, 4),
            "pre_release": is_pre_release,
            "poster_url": bp_row.get("poster_url") if hasattr(bp_row, "get") else None,
            "overview": str(bp_row.get("overview", ""))[:200] if hasattr(bp_row, "get") else "",
            "tomatometer_rating": rt,
            "metacritic_score": mc,
        }

    result = []
    for fest in festivals:
        start = date.fromisoformat(fest["start"])
        end = date.fromisoformat(fest["end"])

        if today < start:
            status = "upcoming"
            days_until = (start - today).days
        elif today <= end:
            status = "active"
            days_until = 0
        else:
            status = "completed"
            days_until = None

        # Confirmed films for this festival — ranked by buzz, capped at 5
        flag_col = fest["flag"]
        confirmed_films = []
        if not flags_df.empty and flag_col in flags_df.columns:
            flagged = flags_df[flags_df[flag_col] == 1].copy()
            flagged["_title_low"] = flagged["title"].str.lower().str.strip()
            rows_with_buzz = []
            for _, row in flagged.iterrows():
                bp_row = bp_lookup.get(row["_title_low"])
                buzz = _buzz_score(bp_row)
                rows_with_buzz.append((buzz, row["title"], bp_row))
            rows_with_buzz.sort(reverse=True)
            # Top 5 by buzz score — these are the films worth watching from the lineup
            confirmed_films = [_film_card(t, r) for _, t, r in rows_with_buzz[:5]]

        result.append({
            "key": fest["key"],
            "name": fest["name"],
            "location": fest["location"],
            "oscar_note": fest["oscar_note"],
            "start_date": fest["start"],
            "end_date": fest["end"],
            "status": status,
            "days_until": days_until,
            "confirmed_films": confirmed_films,
        })

    return result


def load_forecast_cards(path: Path, limit: int = 12):
    df = pd.read_csv(path).head(limit).copy()
    cards = []
    for idx, row in df.reset_index(drop=True).iterrows():
        tomatometer_rating = (
            float(row.get("tomatometer_rating"))
            if pd.notna(row.get("tomatometer_rating"))
            else None
        )
        audience_rating = (
            float(row.get("audience_rating"))
            if pd.notna(row.get("audience_rating"))
            else None
        )
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
                "tomatometer_rating": tomatometer_rating,
                "audience_rating": audience_rating,
                "rt_url": row.get("rt_url"),
                "forecast_season": row.get("forecast_season"),
                "prestige_score": float(row.get("prestige_score", 0)) if pd.notna(row.get("prestige_score")) else None,
                "manual_contender_flag": int(row.get("manual_contender_flag", 0)) if pd.notna(row.get("manual_contender_flag")) else 0,
                "pga_win": _safe_int_col(row, "pga_win"),
                "dga_win": _safe_int_col(row, "dga_win"),
                "sag_win": _safe_int_col(row, "sag_win"),
                "bafta_win": _safe_int_col(row, "bafta_win"),
                "golden_globe_win": _safe_int_col(row, "golden_globe_win"),
                "critics_choice_win": _safe_int_col(row, "critics_choice_win"),
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
                "poster_url": predicted.get("poster_url"),
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
            def _intcol(col):
                v = row.get(col)
                return int(v) if v is not None and str(v) != "nan" else 0

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
                    "poster_url": row.get("poster_url"),
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
                    # Precursor award wins
                    "pga_win": _intcol("pga_win"),
                    "dga_win": _intcol("dga_win"),
                    "sag_win": _intcol("sag_win"),
                    "bafta_win": _intcol("bafta_win"),
                    "golden_globe_win": _intcol("golden_globe_win"),
                    "critics_choice_win": _intcol("critics_choice_win"),
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
        if year != CURRENT_FORECAST_YEAR:
            continue
        df = pd.read_csv(path).copy()
        forecast_season = forecast_season_for_df(df)
        season_guide = FORECAST_SEASON_GUIDE.get(forecast_season, {})
        rows = []
        for _, row in df.head(20).iterrows():
            def _fcol(col):
                v = row.get(col)
                try:
                    return int(float(v)) if v is not None and str(v) != "nan" else 0
                except (ValueError, TypeError):
                    return 0

            rows.append(
                {
                    "film": row.get("title"),
                    "probability": float(row.get("best_picture_probability", 0)),
                    "actual_winner": False,
                    "oscar_nomination_count": None,
                    "tomatometer_rating": (
                        float(row.get("tomatometer_rating"))
                        if pd.notna(row.get("tomatometer_rating"))
                        else None
                    ),
                    "audience_rating": (
                        float(row.get("audience_rating"))
                        if pd.notna(row.get("audience_rating"))
                        else None
                    ),
                    "rt_url": row.get("rt_url"),
                    "momentum_score": None,
                    "poster_url": row.get("poster_url"),
                    "forecast_season": row.get("forecast_season"),
                    "prestige_score": float(row.get("prestige_score", 0)) if pd.notna(row.get("prestige_score")) else None,
                    "manual_contender_flag": int(row.get("manual_contender_flag", 0)) if pd.notna(row.get("manual_contender_flag")) else 0,
                    "pga_win": _fcol("pga_win"),
                    "dga_win": _fcol("dga_win"),
                    "sag_win": _fcol("sag_win"),
                    "bafta_win": _fcol("bafta_win"),
                    "golden_globe_win": _fcol("golden_globe_win"),
                    "critics_choice_win": _fcol("critics_choice_win"),
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


def _card_context(card: dict) -> str:
    """Build a concise context string for a forecast card."""
    parts = [f"Film: {card['title']}"]
    parts.append(f"Current rank: #{card['rank']}")

    movement = card.get("movement")
    delta = card.get("rank_delta")
    if movement == "up":
        parts.append(f"Moved up {delta} spot(s) this week")
    elif movement == "down":
        parts.append(f"Moved down {abs(delta)} spot(s) this week")
    elif movement == "new":
        parts.append("New entry on the board this week")
    else:
        parts.append("No rank change this week")

    prob = card.get("probability", 0)
    parts.append(f"Win probability: {prob * 100:.1f}%")

    awards = []
    for key, label in [
        ("pga_win", "PGA"), ("dga_win", "DGA"), ("sag_win", "SAG"),
        ("bafta_win", "BAFTA"), ("golden_globe_win", "Golden Globe"),
        ("critics_choice_win", "Critics Choice"),
    ]:
        if card.get(key):
            awards.append(label)
    if awards:
        parts.append(f"Precursor wins: {', '.join(awards)}")
    else:
        parts.append("No precursor wins yet")

    if card.get("tomatometer_rating") is not None:
        parts.append(f"Rotten Tomatoes: {int(card['tomatometer_rating'])}%")

    return "\n".join(parts)


def generate_movement_blurbs(cards: list[dict]) -> list[dict]:
    """
    Generate a 1-2 sentence AI blurb for each forecast card explaining
    why it moved up, down, or stayed the same. Skips if ANTHROPIC_API_KEY
    is not set. Falls back gracefully on any error.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[blurbs] ANTHROPIC_API_KEY not set — preserving existing blurbs.")
        # Preserve previously generated blurbs so local rebuilds don't wipe them.
        # Try reading from the current site_data.json first; fall back to git HEAD.
        existing_blurbs: dict[str, str] = {}
        existing_path = Path(__file__).resolve().parent.parent / "site" / "data" / "site_data.json"

        def _load_blurbs_from_json(source: str) -> dict[str, str]:
            try:
                data = json.loads(source)
                return {
                    c.get("title", ""): c.get("movement_blurb", "")
                    for c in data.get("forecast_cards", [])
                    if c.get("movement_blurb")
                }
            except Exception:
                return {}

        # 1. Try on-disk file
        if existing_path.exists():
            try:
                with open(existing_path) as f:
                    existing_blurbs = _load_blurbs_from_json(f.read())
            except Exception:
                pass

        # 2. If disk file had no blurbs (e.g. was overwritten by a no-key build), try git
        if not existing_blurbs:
            try:
                import subprocess
                result = subprocess.run(
                    ["git", "show", "HEAD:site/data/site_data.json"],
                    capture_output=True, text=True, cwd=existing_path.parent.parent.parent
                )
                if result.returncode == 0:
                    existing_blurbs = _load_blurbs_from_json(result.stdout)
                    if existing_blurbs:
                        print(f"[blurbs] Restored {len(existing_blurbs)} blurbs from git HEAD.")
            except Exception:
                pass

        return [
            {**card, "movement_blurb": existing_blurbs.get(card.get("title", ""), card.get("movement_blurb", ""))}
            for card in cards
        ]

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        print("[blurbs] anthropic package not installed — skipping AI blurbs.")
        return cards

    enriched = []
    for card in cards:
        try:
            context = _card_context(card)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=120,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "You are writing short, punchy analyst blurbs for an Oscar prediction site. "
                            "Based on the data below, write 1-2 sentences (max 40 words) explaining why this film "
                            "moved up, down, or stayed put in the Best Picture rankings this week. "
                            "Be specific — mention actual awards or scores. No filler phrases. "
                            "Do not start with the film title.\n\n"
                            f"{context}"
                        ),
                    }
                ],
            )
            blurb = message.content[0].text.strip()
            updated = dict(card)
            updated["movement_blurb"] = blurb
            enriched.append(updated)
            time.sleep(0.3)  # gentle rate limit
        except Exception as exc:
            print(f"[blurbs] Failed for {card.get('title')}: {exc}")
            enriched.append(card)

    return enriched


def generate_actor_movement_blurbs(contenders: list[dict], existing_blurbs: dict) -> list[dict]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # Restore preserved blurbs
        for c in contenders:
            c["movement_blurb"] = existing_blurbs.get(c.get("name", ""), "")
        return contenders
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return contenders

    for c in contenders:
        try:
            noms = c.get("oscar_nominations", 0)
            wins = c.get("oscar_wins", 0)
            hist = f"{wins} Oscar win(s), {noms} nomination(s)" if noms else "no prior Oscar nominations"
            precursors = []
            if c.get("sag_win"): precursors.append("SAG winner")
            elif c.get("sag_nom"): precursors.append("SAG nominee")
            if c.get("globe_win"): precursors.append("Globe winner")
            elif c.get("globe_nom"): precursors.append("Globe nominee")
            if c.get("bafta_win"): precursors.append("BAFTA winner")
            elif c.get("bafta_nom"): precursors.append("BAFTA nominee")
            precursor_str = ", ".join(precursors) if precursors else "no precursor wins yet"
            mvmt = c.get("movement", "new")
            delta = c.get("rank_delta", 0) or 0
            mvmt_str = f"moved up {abs(delta)}" if mvmt == "up" else f"dropped {abs(delta)}" if mvmt == "down" else "new entry" if mvmt == "new" else "holding"

            prompt = (
                f"Actor: {c['name']}, Film: {c['film']}, "
                f"Rank: #{c['rank']} ({mvmt_str}), "
                f"Win probability: {round(c.get('win_probability', 0) * 100)}%, "
                f"Oscar history: {hist}, "
                f"Precursors: {precursor_str}, "
                f"Tomatometer: {int(c.get('tomatometer_rating') or 0)}%, "
                f"Metacritic: {int(c.get('metacritic_score') or 0)}. "
                f"Write a single sharp sentence (max 25 words) explaining their standing."
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                system="You are a terse awards-season analyst writing single-sentence blurbs for a live Oscar contender board. No fluff. Max 25 words.",
                messages=[{"role": "user", "content": prompt}],
            )
            c["movement_blurb"] = msg.content[0].text.strip()
        except Exception:
            c["movement_blurb"] = existing_blurbs.get(c.get("name", ""), "")

    return contenders


def build_category_payload(category: str) -> dict:
    """
    Run the walk-forward backtest for 'actor', 'actress', or 'director' and
    return a payload dict with backtest_rows and accuracy metrics.
    """
    label = CATEGORY_CONFIG[category]["label"]
    print(f"[categories] Running {label} backtest...")
    try:
        summary = backtest_category(category)
    except Exception as exc:
        print(f"[categories] {label} backtest failed: {exc}")
        return {
            "label": label,
            "error": str(exc),
            "backtest_rows": [],
            "accuracy": 0.0,
            "correct_count": 0,
            "total_count": 0,
            "first_year": None,
            "last_year": None,
            "live_contenders": [],
        }

    if summary.empty:
        return {
            "label": label,
            "backtest_rows": [],
            "accuracy": 0.0,
            "correct_count": 0,
            "total_count": 0,
            "first_year": None,
            "last_year": None,
            "live_contenders": [],
        }

    accuracy = float(summary["correct"].mean())
    rows = []
    for _, row in summary.iterrows():
        r = {
            "year_film": int(row["year_film"]),
            "predicted_winner": row["predicted_winner"],
            "predicted_film": row.get("predicted_film"),
            "predicted_probability": float(row["predicted_probability"]),
            "actual_winner": row["actual_winner"],
            "actual_film": row.get("actual_film"),
            "correct": bool(row["correct"]),
            "runner_up": row.get("runner_up"),
            "runner_up_film": row.get("runner_up_film"),
        }
        # Include available precursor signals
        for sig in ("sag_win", "dga_win", "globe_win", "bafta_win"):
            v = row.get(sig)
            if v is not None and str(v) != "nan":
                r[sig] = int(float(v))
        rows.append(r)

    # Load live contenders for the current year
    year = datetime.now().year
    month = datetime.now().month
    # Jan-Mar = Oscar window for prior year's films
    if month <= 3:
        year = year - 1

    # Map category → CSV filename and precursor signal columns
    CATEGORY_LIVE_CONFIG = {
        "actor": {
            "csv": f"future_actor_predictions_{year}.csv",
            "precursor_cols": ["sag_nom", "sag_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"],
            "oscar_category": "ACTOR IN A LEADING ROLE",
            "data_key": "actor_data",
        },
        "actress": {
            "csv": f"future_actress_predictions_{year}.csv",
            "precursor_cols": ["sag_nom", "sag_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"],
            "oscar_category": "ACTRESS IN A LEADING ROLE",
            "data_key": "actress_data",
        },
        "director": {
            "csv": f"future_director_predictions_{year}.csv",
            "precursor_cols": ["dga_nom", "dga_win", "globe_nom", "globe_win", "bafta_nom", "bafta_win"],
            "oscar_category": "DIRECTING",
            "data_key": "director_data",
        },
    }

    live_contenders = []
    if category in CATEGORY_LIVE_CONFIG:
        cfg = CATEGORY_LIVE_CONFIG[category]
        live_path = ROOT / "output" / cfg["csv"]
        precursor_cols = cfg["precursor_cols"]

        if live_path.exists():
            live_df = pd.read_csv(live_path)
            # Sort by win_probability descending and cap at top 20
            if "win_probability" in live_df.columns:
                live_df = live_df.sort_values("win_probability", ascending=False).head(20).reset_index(drop=True)
                live_df["rank"] = live_df.index + 1
            for _, row in live_df.iterrows():
                lc = {
                    "rank": int(row.get("rank", 0)),
                    "name": str(row.get("name", "")),
                    "film": str(row.get("film", "")),
                    "win_probability": float(row.get("win_probability", 0)),
                    "prior_nominations": int(row.get("prior_nominations", 0) or 0),
                    "prior_wins": int(row.get("prior_wins", 0) or 0),
                    "profile_url": str(row.get("profile_url", "") or ""),
                    "tomatometer_rating": float(row.get("tomatometer_rating", 0) or 0),
                    "metacritic_score": float(row.get("metacritic_score", 0) or 0),
                    "forecast_season": str(row.get("forecast_season", "early")),
                    "previous_rank": int(row["previous_rank"]) if pd.notna(row.get("previous_rank")) else None,
                    "rank_delta": int(row["rank_delta"]) if pd.notna(row.get("rank_delta")) else None,
                    "movement": str(row.get("movement", "new")),
                    "oscar_nominations": 0,
                    "oscar_wins": 0,
                    "movement_blurb": "",
                }
                # Add precursor signal columns
                for col in precursor_cols:
                    lc[col] = int(row.get(col, 0) or 0)
                live_contenders.append(lc)

        # Oscar history badges
        if live_contenders:
            oscar_lookup = build_oscar_acting_lookup(cfg["oscar_category"])
            for lc in live_contenders:
                key = " ".join(lc["name"].upper().split())
                hist = oscar_lookup.get(key, {"nominations": 0, "wins": 0})
                lc["oscar_nominations"] = hist["nominations"]
                lc["oscar_wins"] = hist["wins"]

        # AI movement blurbs — runs for actor, actress, and director
        if live_contenders:
            data_key = CATEGORY_LIVE_CONFIG[category]["data_key"]
            existing_blurbs = {}
            try:
                with open(SITE_DATA_PATH) as f:
                    prev = json.load(f)
                    for lc in prev.get(data_key, {}).get("live_contenders", []):
                        if lc.get("movement_blurb"):
                            existing_blurbs[lc["name"]] = lc["movement_blurb"]
            except Exception:
                pass
            live_contenders = generate_actor_movement_blurbs(live_contenders, existing_blurbs)

    # Recent races — last 10 backtest years, newest first, for the UI race grid
    recent_race_rows = summary.sort_values("year_film").tail(10)
    recent_races = []
    for _, rr in recent_race_rows.iterrows():
        recent_races.append({
            "year_film": int(rr["year_film"]),
            "predicted_winner": rr.get("predicted_winner"),
            "predicted_film": rr.get("predicted_film"),
            "predicted_probability": float(rr.get("predicted_probability", 0)),
            "actual_winner": rr.get("actual_winner"),
            "actual_film": rr.get("actual_film"),
            "correct": bool(rr.get("correct", False)),
            "runner_up": rr.get("runner_up"),
            "runner_up_film": rr.get("runner_up_film"),
            "runner_up_probability": float(rr["runner_up_probability"]) if pd.notna(rr.get("runner_up_probability")) else None,
            "sag_win": int(rr["sag_win"]) if pd.notna(rr.get("sag_win")) else None,
            "dga_win": int(rr["dga_win"]) if pd.notna(rr.get("dga_win")) else None,
            "globe_win": int(rr.get("globe_win", 0)),
            "bafta_win": int(rr.get("bafta_win", 0)),
        })

    return {
        "label": label,
        "backtest_rows": rows,
        "accuracy": accuracy,
        "correct_count": int(summary["correct"].sum()),
        "total_count": int(len(summary)),
        "first_year": int(summary["year_film"].min()),
        "last_year": int(summary["year_film"].max()),
        "live_contenders": live_contenders,
        "recent_races": recent_races,
    }


def build_payload():
    raw_df = load_data()
    model_df = prepare_data(raw_df)

    forecast_year, forecast_path = find_latest_future_forecast()
    forecast_cards = load_forecast_cards(forecast_path, limit=12)
    previous_forecast_cards = load_previous_forecast_cards(forecast_year, limit=50)
    forecast_cards = add_rank_changes(forecast_cards, previous_forecast_cards)
    forecast_cards = generate_movement_blurbs(forecast_cards)
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
        "festival_watch": build_festival_watch_payload(forecast_year),
        "season_modes": season_modes,
        "actual_winners": build_actual_winners(model_df, start_year=SITE_HISTORY_START_YEAR),
        "actor_data": build_category_payload("actor"),
        "actress_data": build_category_payload("actress"),
        "director_data": build_category_payload("director"),
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
