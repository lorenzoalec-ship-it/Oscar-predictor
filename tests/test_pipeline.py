"""
Unit and integration tests for the Oscar predictor pipeline.

Run with:
    pytest tests/test_pipeline.py -v
"""
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make src importable without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pipeline import clean_text, genre_flag, parse_percent, build_oscar_film_table
from future_best_picture import (
    normalize,
    clip01,
    parse_numeric,
    infer_season,
    add_common_features,
    has_genre_id,
)


# ---------------------------------------------------------------------------
# pipeline.clean_text
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_lowercases(self):
        result = clean_text(pd.Series(["The Godfather"]))
        assert result.iloc[0] == "the godfather"

    def test_strips_punctuation(self):
        result = clean_text(pd.Series(["Schindler's List!"]))
        assert result.iloc[0] == "schindler s list"

    def test_collapses_whitespace(self):
        result = clean_text(pd.Series(["  Mul  ti  ple  "]))
        assert result.iloc[0] == "mul ti ple"

    def test_handles_nan(self):
        result = clean_text(pd.Series([None]))
        assert isinstance(result.iloc[0], str)


# ---------------------------------------------------------------------------
# pipeline.parse_percent
# ---------------------------------------------------------------------------

class TestParsePercent:
    def test_strips_percent_sign(self):
        result = parse_percent(pd.Series(["95%"]))
        assert result.iloc[0] == 95.0

    def test_plain_number(self):
        result = parse_percent(pd.Series(["72"]))
        assert result.iloc[0] == 72.0

    def test_invalid_returns_nan(self):
        result = parse_percent(pd.Series(["N/A"]))
        assert pd.isna(result.iloc[0])

    def test_nan_input(self):
        result = parse_percent(pd.Series([None]))
        assert pd.isna(result.iloc[0])


# ---------------------------------------------------------------------------
# pipeline.genre_flag
# ---------------------------------------------------------------------------

class TestGenreFlag:
    def test_matches(self):
        result = genre_flag(pd.Series(["Drama, History"]), "Drama")
        assert result.iloc[0] == 1

    def test_no_match(self):
        result = genre_flag(pd.Series(["Comedy"]), "Drama")
        assert result.iloc[0] == 0

    def test_case_insensitive(self):
        result = genre_flag(pd.Series(["DRAMA"]), "drama")
        assert result.iloc[0] == 1


# ---------------------------------------------------------------------------
# future_best_picture.normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_basic_normalization(self):
        result = normalize(pd.Series([50.0]), scale=100.0)
        assert result.iloc[0] == pytest.approx(0.5)

    def test_clips_above_one(self):
        result = normalize(pd.Series([200.0]), scale=100.0)
        assert result.iloc[0] == pytest.approx(1.0)

    def test_clips_below_zero(self):
        result = normalize(pd.Series([-10.0]), scale=100.0)
        assert result.iloc[0] == pytest.approx(0.0)

    def test_zero_scale_returns_zero(self):
        result = normalize(pd.Series([50.0, 100.0]), scale=0)
        assert (result == 0.0).all()

    def test_nan_input_returns_zero(self):
        result = normalize(pd.Series([None]), scale=100.0)
        assert result.iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# future_best_picture.infer_season
# ---------------------------------------------------------------------------

class TestInferSeason:
    def test_override_respected(self):
        assert infer_season(2025, override="precursor") == "precursor"

    def test_future_year_is_early(self):
        # A year well in the future should always be "early"
        assert infer_season(2099) == "early"

    def test_valid_seasons(self):
        valid = {"early", "festival", "precursor", "post_nomination"}
        for year in range(2020, 2030):
            season = infer_season(year)
            assert season in valid, f"Unexpected season '{season}' for year {year}"


# ---------------------------------------------------------------------------
# future_best_picture.has_genre_id
# ---------------------------------------------------------------------------

class TestHasGenreId:
    def test_matches_single(self):
        result = has_genre_id(pd.Series(["18"]), "18")
        assert result.iloc[0] == 1

    def test_matches_in_list(self):
        result = has_genre_id(pd.Series(["10749,18,36"]), "18")
        assert result.iloc[0] == 1

    def test_no_partial_match(self):
        # genre id 18 should NOT match 180
        result = has_genre_id(pd.Series(["180,36"]), "18")
        assert result.iloc[0] == 0

    def test_no_match(self):
        result = has_genre_id(pd.Series(["36,10749"]), "18")
        assert result.iloc[0] == 0


# ---------------------------------------------------------------------------
# pipeline.build_oscar_film_table (integration test on fixture data)
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_oscars():
    return pd.DataFrame(
        {
            "year_film": [2000, 2000, 2000, 2000, 2001],
            "film": ["Gladiator", "Gladiator", "Erin Brockovich", "Traffic", "A Beautiful Mind"],
            "category": [
                "BEST PICTURE",
                "BEST DIRECTING",
                "BEST PICTURE",
                "BEST PICTURE",
                "BEST PICTURE",
            ],
            "winner": [True, False, False, False, True],
            "name": ["Ridley Scott", "Ridley Scott", "Steven Soderbergh", "Steven Soderbergh", "Ron Howard"],
        }
    )


class TestBuildOscarFilmTable:
    def test_returns_dataframe(self, minimal_oscars):
        result = build_oscar_film_table(minimal_oscars)
        assert isinstance(result, pd.DataFrame)

    def test_best_picture_winner_flagged(self, minimal_oscars):
        result = build_oscar_film_table(minimal_oscars)
        winner_row = result[result["film_key"] == "gladiator"]
        assert not winner_row.empty
        assert winner_row.iloc[0]["best_picture_winner"] == 1

    def test_non_winner_not_flagged(self, minimal_oscars):
        result = build_oscar_film_table(minimal_oscars)
        row = result[result["film_key"] == "erin brockovich"]
        assert not row.empty
        assert row.iloc[0]["best_picture_winner"] == 0

    def test_oscar_nomination_count(self, minimal_oscars):
        result = build_oscar_film_table(minimal_oscars)
        # Gladiator has 2 rows (Best Picture + Best Directing)
        gladiator = result[result["film_key"] == "gladiator"]
        assert gladiator.iloc[0]["oscar_nomination_count"] == 2

    def test_all_years_present(self, minimal_oscars):
        result = build_oscar_film_table(minimal_oscars)
        assert set(result["year_film"]) == {2000, 2001}
