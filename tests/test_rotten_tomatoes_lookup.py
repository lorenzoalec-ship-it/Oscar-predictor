import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rotten_tomatoes_lookup import choose_best_movie_hit, normalize_title, title_variants


def _hit(title, year, vanity, critics_score, *, aka=None):
    return {
        "title": title,
        "titles": [title],
        "aka": aka or [],
        "releaseYear": year,
        "vanity": vanity,
        "type": "movie",
        "titleType": "main",
        "rottenTomatoes": {"criticsScore": critics_score},
    }


def test_normalize_title_strips_punctuation_and_case():
    assert normalize_title("Schindler's List!") == "schindler s list"


def test_title_variants_include_articleless_version():
    variants = title_variants("The Father")
    assert "the father" in variants
    assert "father" in variants


def test_choose_best_movie_hit_prefers_exact_title_over_partial_match():
    hits = [
        _hit("In the Name of the Father", 1993, "in_the_name_of_the_father", 94),
        _hit("The Father", 2020, "the_father_2021", 98),
    ]

    best_hit, details = choose_best_movie_hit("The Father", 2020, hits)

    assert best_hit is not None
    assert best_hit["vanity"] == "the_father_2021"
    assert details["match_score"] >= 150


def test_choose_best_movie_hit_rejects_low_confidence_matches():
    hits = [
        _hit("Father of Nations", 2022, "father_of_nations", 0),
        _hit("Show Me the Father", 2021, "show_me_the_father", 0),
    ]

    best_hit, details = choose_best_movie_hit("The Father", 2020, hits)

    assert best_hit is None
    assert "low-confidence" in details["match_reason"] or "ambiguous-match" in details["match_reason"]
