import pandas as pd
import re


OSCARS_PATH = "data/raw/the_oscar_award.csv"
MOVIES_PATH = "data/raw/16k_Movies.csv"
MOVIE_MANUAL_OVERRIDES_PATH = "data/raw/movie_manual_overrides.csv"
GLOBES_PATH = "data/raw/golden_globe_awards.csv"
SAG_PATH = "data/raw/screen_actor_guild_awards.csv"
BAFTA_PATH = "data/raw/bafta_films.csv"
PGA_PATH = "data/raw/pga_awards.csv"
DGA_PATH = "data/raw/dga_awards.csv"
CRITICS_CHOICE_PATH = "data/raw/critics_choice_awards.csv"
GLOBES_RECENT_SUMMARY_PATH = "data/raw/golden_globe_recent_summary.csv"
SAG_RECENT_SUMMARY_PATH = "data/raw/sag_recent_summary.csv"
BAFTA_RECENT_SUMMARY_PATH = "data/raw/bafta_recent_summary.csv"
PGA_RECENT_SUMMARY_PATH = "data/raw/pga_recent_summary.csv"
DGA_RECENT_SUMMARY_PATH = "data/raw/dga_recent_summary.csv"
CRITICS_CHOICE_RECENT_SUMMARY_PATH = "data/raw/critics_choice_recent_summary.csv"
RT_RECENT_SUMMARY_PATH = "data/raw/rotten_tomatoes_recent_summary.csv"
FESTIVAL_METACRITIC_SUMMARY_PATH = "data/raw/festival_metacritic_summary.csv"
RT_OLD_PATH = "data/raw/rotten_tomatoes_movies_legacy.csv"
RT_NEW_PATH = "data/raw/rotten_tomatoes_movies_recent.csv"
MIN_FILM_YEAR = 1927


def load_optional_csv(path: str, columns: list[str]) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=columns)

def parse_percent(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace("%", "", regex=False)
        .replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def parse_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def parse_release_date(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(r"^Released\s+", "", regex=True)
        .replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    )

    parsed_dates = pd.to_datetime(cleaned, errors="coerce")
    extracted_year = pd.to_numeric(cleaned.str.extract(r"(\d{4})")[0], errors="coerce")
    return parsed_dates, extracted_year


def load_rt_movies():
    rt_old = pd.read_csv(RT_OLD_PATH)
    rt_new = pd.read_csv(RT_NEW_PATH)

    rt_old.columns = (
        rt_old.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    )
    rt_new.columns = (
        rt_new.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    )

    old_dates = pd.to_datetime(rt_old["in_theaters_date"], errors="coerce")
    old_tbl = pd.DataFrame(
        {
            "film_key": clean_text(rt_old["movie_title"]),
            "rt_movie_title": rt_old["movie_title"],
            "rt_url": pd.NA,
            "rt_in_theaters_date": old_dates,
            "rt_release_year": old_dates.dt.year,
            "rt_release_month": old_dates.dt.month,
            "tomatometer_rating": pd.to_numeric(
                rt_old["tomatometer_rating"], errors="coerce"
            ),
            "audience_rating": pd.to_numeric(rt_old["audience_rating"], errors="coerce"),
            "rt_source": "legacy",
        }
    )

    new_dates, new_years = parse_release_date(rt_new["release_date"])
    new_tbl = pd.DataFrame(
        {
            "film_key": clean_text(rt_new["title"]),
            "rt_movie_title": rt_new["title"],
            "rt_url": rt_new["url"] if "url" in rt_new.columns else pd.NA,
            "rt_in_theaters_date": new_dates,
            "rt_release_year": new_dates.dt.year.fillna(new_years),
            "rt_release_month": new_dates.dt.month,
            "tomatometer_rating": parse_percent(rt_new["critic_score"]),
            "audience_rating": parse_percent(rt_new["audience_score"]),
            "rt_source": "recent",
        }
    )

    rt = pd.concat([old_tbl, new_tbl], ignore_index=True)
    rt["match_quality"] = (
        rt["tomatometer_rating"].notna().astype(int) * 2
        + rt["rt_release_month"].notna().astype(int)
        + rt["rt_in_theaters_date"].notna().astype(int)
    )
    rt["source_priority"] = rt["rt_source"].eq("recent").astype(int)

    rt = rt.sort_values(
        ["film_key", "rt_release_year", "match_quality", "source_priority"],
        ascending=[True, True, False, False],
    )
    pre_dedup = len(rt)
    rt = rt.drop_duplicates(subset=["film_key", "rt_release_year"], keep="first")
    dropped = pre_dedup - len(rt)
    if dropped:
        print(f"[pipeline] RT dedup: dropped {dropped} duplicate film-year records (kept highest-quality source).")

    return rt.drop(columns=["match_quality", "source_priority"])

FINAL_DATA_PATH = "output/model_data.csv"



def clean_text(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.lower()
        .str.replace(r"[^a-z0-9]+", " ", regex=True)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def split_people(value) -> list[str]:
    if pd.isna(value):
        return []

    text = str(value).replace("\n", ",").replace("/", ",")
    parts = [part.strip() for part in text.split(",")]
    return [part for part in parts if part]


def extract_distributor_from_description(value):
    if pd.isna(value):
        return pd.NA

    text = str(value).strip()
    bracket_match = re.search(r"\[([^\]]+)\]\s*$", text)
    if bracket_match:
        return bracket_match.group(1).strip()

    paren_match = re.search(r"\(([^()]{2,80})\)\s*$", text)
    if paren_match:
        return paren_match.group(1).strip()

    return pd.NA


def genre_flag(series: pd.Series, token: str) -> pd.Series:
    return series.astype(str).str.contains(token, case=False, na=False).astype(int)


def standardize_columns(*dfs):
    cleaned = []
    for df in dfs:
        df = df.copy()
        df.columns = (
            df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
        )
        cleaned.append(df)
    return cleaned


def load_data():
    oscars = pd.read_csv(OSCARS_PATH)
    movies = pd.read_csv(MOVIES_PATH)
    movie_manual_overrides = load_optional_csv(
        MOVIE_MANUAL_OVERRIDES_PATH,
        ["year_film", "film", "movie_rating", "movie_vote_count"],
    )
    globes = pd.read_csv(GLOBES_PATH)
    sag = pd.read_csv(SAG_PATH)
    bafta = pd.read_csv(BAFTA_PATH)
    pga = load_optional_csv(PGA_PATH, ["year", "film", "winner"])
    dga = load_optional_csv(DGA_PATH, ["year", "film", "winner"])
    critics_choice = load_optional_csv(CRITICS_CHOICE_PATH, ["year", "film", "winner"])
    globes_recent = pd.read_csv(GLOBES_RECENT_SUMMARY_PATH)
    sag_recent = pd.read_csv(SAG_RECENT_SUMMARY_PATH)
    bafta_recent = pd.read_csv(BAFTA_RECENT_SUMMARY_PATH)
    pga_recent = load_optional_csv(PGA_RECENT_SUMMARY_PATH, ["year_film", "film", "pga_nom_count", "pga_win_count"])
    dga_recent = load_optional_csv(DGA_RECENT_SUMMARY_PATH, ["year_film", "film", "dga_nom_count", "dga_win_count"])
    critics_choice_recent = load_optional_csv(
        CRITICS_CHOICE_RECENT_SUMMARY_PATH,
        ["year_film", "film", "critics_choice_nom_count", "critics_choice_win_count"],
    )
    rt_recent = pd.read_csv(RT_RECENT_SUMMARY_PATH)
    festival_metacritic = pd.read_csv(FESTIVAL_METACRITIC_SUMMARY_PATH)
    rt_movies = load_rt_movies()
    return (
        oscars,
        movies,
        movie_manual_overrides,
        globes,
        sag,
        bafta,
        pga,
        dga,
        critics_choice,
        globes_recent,
        sag_recent,
        bafta_recent,
        pga_recent,
        dga_recent,
        critics_choice_recent,
        rt_recent,
        festival_metacritic,
        rt_movies,
    )


def build_oscar_film_table(oscars: pd.DataFrame) -> pd.DataFrame:
    df = oscars.copy()
    df = df[df["film"].notna()].copy()

    df["film_key"] = clean_text(df["film"])
    df["winner"] = df["winner"].astype(str).str.lower().eq("true")

    film_level = (
        df.groupby(["year_film", "film_key", "film"], as_index=False)
        .agg(
            oscar_nomination_count=("film", "size"),
            oscar_win_count=("winner", "sum"),
        )
    )

    film_level["won_oscar"] = (film_level["oscar_win_count"] > 0).astype(int)

    best_picture_categories = {"BEST PICTURE", "BEST MOTION PICTURE"}
    best_picture_df = df[
        df["category"].astype(str).str.upper().isin(best_picture_categories)
    ].copy()

    best_picture_level = (
        best_picture_df.groupby(["year_film", "film_key"], as_index=False)
        .agg(
            best_picture_nominee=("film_key", "size"),
            best_picture_winner=("winner", "max"),
        )
    )

    best_picture_level["best_picture_nominee"] = (
        best_picture_level["best_picture_nominee"] > 0
    ).astype(int)
    best_picture_level["best_picture_winner"] = (
        best_picture_level["best_picture_winner"] > 0
    ).astype(int)

    film_level = film_level.merge(
        best_picture_level,
        on=["year_film", "film_key"],
        how="left",
    )
    film_level["best_picture_nominee"] = film_level["best_picture_nominee"].fillna(0).astype(int)
    film_level["best_picture_winner"] = film_level["best_picture_winner"].fillna(0).astype(int)

    film_level = film_level[film_level["year_film"] >= MIN_FILM_YEAR].copy()

    return film_level


def build_movies_table(movies: pd.DataFrame) -> pd.DataFrame:
    df = movies.copy()

    if "unnamed:_0" in df.columns:
        df = df.drop(columns=["unnamed:_0"])

    df["film_key"] = clean_text(df["title"])
    df["movie_release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    df["movie_release_year"] = df["movie_release_date"].dt.year
    df["movie_release_month"] = df["movie_release_date"].dt.month
    df["movie_distributor"] = df["description"].apply(extract_distributor_from_description)
    if "rating" in df.columns:
        df["rating"] = parse_number(df["rating"])
    if "no_of_persons_voted" in df.columns:
        df["no_of_persons_voted"] = parse_number(df["no_of_persons_voted"])

    df = df.rename(
        columns={
            "title": "movie_title",
            "rating": "movie_rating",
            "no_of_persons_voted": "movie_vote_count",
            "directed_by": "movie_directed_by",
            "genres": "movie_genres",
            "duration": "movie_duration",
        }
    )

    keep_cols = [
        "film_key",
        "movie_title",
        "movie_release_date",
        "movie_release_year",
        "movie_release_month",
        "movie_rating",
        "movie_vote_count",
        "movie_directed_by",
        "movie_genres",
        "movie_duration",
        "movie_distributor",
    ]

    return df[keep_cols].drop_duplicates(subset=["film_key"])


def build_movie_manual_overrides_table(overrides: pd.DataFrame) -> pd.DataFrame:
    df = overrides.copy()
    if df.empty:
        return pd.DataFrame(
            columns=["year_film", "film_key", "movie_rating_override", "movie_vote_count_override"]
        )

    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = clean_text(df["film"])
    df["movie_rating_override"] = pd.to_numeric(df.get("movie_rating"), errors="coerce")
    df["movie_vote_count_override"] = parse_number(df.get("movie_vote_count"))

    return df[
        ["year_film", "film_key", "movie_rating_override", "movie_vote_count_override"]
    ].drop_duplicates(subset=["year_film", "film_key"], keep="first")


def build_rt_movies_table(rt_movies: pd.DataFrame) -> pd.DataFrame:
    df = rt_movies.copy()

    df.columns = (
        df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    )

    required_cols = [
        "film_key",
        "rt_movie_title",
        "rt_url",
        "rt_in_theaters_date",
        "rt_release_year",
        "rt_release_month",
        "tomatometer_rating",
        "audience_rating",
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise KeyError(f"Missing expected RT columns: {missing_cols}")

    return df[required_cols].drop_duplicates(subset=["film_key", "rt_release_year"], keep="first")


def build_recent_rt_summary_table(rt_recent: pd.DataFrame) -> pd.DataFrame:
    df = rt_recent.copy()
    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = clean_text(df["film"])
    df["tomatometer_rating"] = pd.to_numeric(df["tomatometer_rating"], errors="coerce")
    df["audience_rating"] = pd.to_numeric(df.get("audience_rating"), errors="coerce")
    df["rt_release_month"] = pd.to_numeric(df.get("rt_release_month"), errors="coerce")
    return df[
        [
            "year_film",
            "film_key",
            "film",
            "tomatometer_rating",
            "audience_rating",
            "rt_release_month",
        ]
    ].drop_duplicates(subset=["year_film", "film_key"], keep="first")


def build_festival_metacritic_table(summary_df: pd.DataFrame) -> pd.DataFrame:
    df = summary_df.copy()
    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = clean_text(df["film"])

    numeric_cols = [
        "metacritic_score",
        "cannes_flag",
        "venice_flag",
        "tiff_flag",
        "telluride_flag",
        "sundance_flag",
        "sxsw_flag",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[
        [
            "year_film",
            "film_key",
            "metacritic_score",
            "cannes_flag",
            "venice_flag",
            "tiff_flag",
            "telluride_flag",
            "sundance_flag",
            "sxsw_flag",
        ]
    ].drop_duplicates(subset=["year_film", "film_key"], keep="first")


def combine_award_features(
    raw_grouped: pd.DataFrame,
    summary_df: pd.DataFrame,
    nom_col: str,
    win_col: str,
    flag_col: str,
) -> pd.DataFrame:
    combined = pd.concat([raw_grouped, summary_df], ignore_index=True, sort=False)
    combined["source_priority"] = pd.to_numeric(
        combined.get("source_priority"), errors="coerce"
    ).fillna(0)
    combined["year_film"] = pd.to_numeric(combined["year_film"], errors="coerce")
    combined = combined.dropna(subset=["year_film", "film_key"]).copy()
    combined["year_film"] = combined["year_film"].astype(int)
    combined = combined.sort_values(
        ["year_film", "film_key", "source_priority"],
        ascending=[True, True, False],
    )
    combined = combined.drop_duplicates(subset=["year_film", "film_key"], keep="first")
    combined[flag_col] = (pd.to_numeric(combined[win_col], errors="coerce").fillna(0) > 0).astype(int)
    return combined[["year_film", "film_key", nom_col, win_col, flag_col]]


def build_generic_award_features(
    raw_df: pd.DataFrame,
    recent_df: pd.DataFrame,
    nom_col: str,
    win_col: str,
    flag_col: str,
    raw_year_column: str = "year",
    raw_film_column_candidates: tuple[str, ...] = ("film", "show", "nominee", "title", "picture", "work"),
    raw_winner_column_candidates: tuple[str, ...] = ("winner", "win", "won", "result", "status"),
    year_offset: int = 0,
) -> pd.DataFrame:
    raw_grouped = pd.DataFrame(columns=["year_film", "film_key", nom_col, win_col, "source_priority"])
    raw = raw_df.copy()
    if not raw.empty:
        year_column = raw_year_column if raw_year_column in raw.columns else None
        film_column = next((col for col in raw_film_column_candidates if col in raw.columns), None)
        winner_column = next((col for col in raw_winner_column_candidates if col in raw.columns), None)

        if year_column and film_column:
            year_values = pd.to_numeric(
                raw[year_column].astype(str).str.extract(r"(\d{4})")[0],
                errors="coerce",
            )
            raw["year_film"] = year_values + year_offset
            raw["film_key"] = clean_text(raw[film_column])
            if winner_column:
                winner_text = raw[winner_column].astype(str)
                raw["_winner"] = winner_text.str.contains(
                    r"true|yes|won|winner",
                    case=False,
                    na=False,
                    regex=True,
                )
            else:
                raw["_winner"] = False

            raw_grouped = (
                raw.dropna(subset=["year_film", "film_key"])
                .groupby(["year_film", "film_key"], as_index=False)
                .agg(
                    **{
                        nom_col: ("film_key", "size"),
                        win_col: ("_winner", "sum"),
                    }
                )
            )
            raw_grouped["source_priority"] = 0

    summary_df = recent_df.copy()
    if summary_df.empty:
        summary_df = pd.DataFrame(columns=["year_film", "film", nom_col, win_col, "source_priority"])
    summary_df["year_film"] = pd.to_numeric(summary_df.get("year_film"), errors="coerce")
    summary_df["film_key"] = clean_text(summary_df.get("film"))
    summary_df["source_priority"] = 1

    return combine_award_features(
        raw_grouped,
        summary_df,
        nom_col,
        win_col,
        flag_col,
    )


def build_globes_features(globes: pd.DataFrame, globes_recent: pd.DataFrame) -> pd.DataFrame:
    df = globes.copy()
    df = df[df["film"].notna()].copy()

    df["year_film"] = pd.to_numeric(df["year_film"], errors="coerce")
    df["film_key"] = clean_text(df["film"])
    df["win"] = df["win"].astype(str).str.lower().eq("true")

    raw_grouped = (
        df.groupby(["year_film", "film_key"], as_index=False)
        .agg(
            globe_nom_count=("film_key", "size"),
            globe_win_count=("win", "sum"),
        )
    )
    raw_grouped["source_priority"] = 0

    summary_df = globes_recent.copy()
    summary_df["year_film"] = pd.to_numeric(summary_df["year_film"], errors="coerce")
    summary_df["film_key"] = clean_text(summary_df["film"])
    summary_df["source_priority"] = 1

    return combine_award_features(
        raw_grouped,
        summary_df,
        "globe_nom_count",
        "globe_win_count",
        "golden_globe_win",
    )


def build_sag_features(sag: pd.DataFrame, sag_recent: pd.DataFrame) -> pd.DataFrame:
    df = sag.copy()
    df = df[df["show"].notna()].copy()

    ceremony_year = pd.to_numeric(
        df["year"].astype(str).str.extract(r"(\d{4})")[0],
        errors="coerce",
    )
    df["year_film"] = ceremony_year - 1
    df["film_key"] = clean_text(df["show"])
    df["won"] = df["won"].astype(str).str.lower().eq("true")
    df["category_key"] = (
        df["category"]
        .astype(str)
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    raw_grouped = (
        df.dropna(subset=["year_film"])
        .groupby(["year_film", "film_key"], as_index=False)
        .agg(
            # Count distinct SAG categories per film, not performer rows.
            sag_nom_count=("category_key", "nunique"),
            sag_win_count=("category_key", lambda series: series[df.loc[series.index, "won"]].nunique()),
        )
    )
    raw_grouped["source_priority"] = 0

    summary_df = sag_recent.copy()
    summary_df["year_film"] = pd.to_numeric(summary_df["year_film"], errors="coerce")
    summary_df["film_key"] = clean_text(summary_df["film"])
    summary_df["source_priority"] = 1

    return combine_award_features(
        raw_grouped,
        summary_df,
        "sag_nom_count",
        "sag_win_count",
        "sag_win",
    )


def build_bafta_features(bafta: pd.DataFrame, bafta_recent: pd.DataFrame) -> pd.DataFrame:
    df = bafta.copy()
    df = df[df["nominee"].notna()].copy()

    df["year_film"] = pd.to_numeric(df["year"], errors="coerce") - 1
    df["film_key"] = clean_text(df["nominee"])
    df["winner"] = df["winner"].astype(str).str.lower().eq("true")

    raw_grouped = (
        df.dropna(subset=["year_film"])
        .groupby(["year_film", "film_key"], as_index=False)
        .agg(
            bafta_nom_count=("film_key", "size"),
            bafta_win_count=("winner", "sum"),
        )
    )
    raw_grouped["source_priority"] = 0

    summary_df = bafta_recent.copy()
    summary_df["year_film"] = pd.to_numeric(summary_df["year_film"], errors="coerce")
    summary_df["film_key"] = clean_text(summary_df["film"])
    summary_df["source_priority"] = 1

    return combine_award_features(
        raw_grouped,
        summary_df,
        "bafta_nom_count",
        "bafta_win_count",
        "bafta_win",
    )


def build_pga_features(pga: pd.DataFrame, pga_recent: pd.DataFrame) -> pd.DataFrame:
    return build_generic_award_features(
        pga,
        pga_recent,
        "pga_nom_count",
        "pga_win_count",
        "pga_win",
        raw_year_column="year",
        year_offset=-1,
    )


def build_dga_features(dga: pd.DataFrame, dga_recent: pd.DataFrame) -> pd.DataFrame:
    return build_generic_award_features(
        dga,
        dga_recent,
        "dga_nom_count",
        "dga_win_count",
        "dga_win",
        raw_year_column="year",
        year_offset=-1,
    )


def build_critics_choice_features(
    critics_choice: pd.DataFrame,
    critics_choice_recent: pd.DataFrame,
) -> pd.DataFrame:
    return build_generic_award_features(
        critics_choice,
        critics_choice_recent,
        "critics_choice_nom_count",
        "critics_choice_win_count",
        "critics_choice_win",
        raw_year_column="year",
        year_offset=-1,
    )


def build_director_history_features(
    oscars: pd.DataFrame,
    oscars_film: pd.DataFrame,
    movies_tbl: pd.DataFrame,
) -> pd.DataFrame:
    directing_df = oscars.copy()
    directing_df = directing_df[
        directing_df["category"].astype(str).str.contains("DIRECTING", case=False, na=False)
    ].copy()
    directing_df = directing_df[directing_df["name"].notna()].copy()

    directing_df["winner"] = directing_df["winner"].astype(str).str.lower().eq("true")
    directing_df["director_key"] = clean_text(directing_df["name"])

    yearly_directing = (
        directing_df.groupby(["director_key", "year_film"], as_index=False)
        .agg(
            directing_nomination_count=("director_key", "size"),
            directing_win_count=("winner", "sum"),
        )
        .sort_values(["director_key", "year_film"])
    )

    yearly_directing["director_prior_directing_nominations"] = (
        yearly_directing.groupby("director_key")["directing_nomination_count"]
        .cumsum()
        .sub(yearly_directing["directing_nomination_count"])
    )
    yearly_directing["director_prior_directing_wins"] = (
        yearly_directing.groupby("director_key")["directing_win_count"]
        .cumsum()
        .sub(yearly_directing["directing_win_count"])
    )

    film_directors = oscars_film[["year_film", "film_key"]].merge(
        movies_tbl[["film_key", "movie_directed_by"]],
        on="film_key",
        how="left",
    )
    film_directors["director_names"] = film_directors["movie_directed_by"].apply(split_people)
    film_directors = film_directors.explode("director_names")
    film_directors = film_directors[film_directors["director_names"].notna()].copy()
    film_directors["director_key"] = clean_text(film_directors["director_names"])

    film_directors = film_directors.merge(
        yearly_directing[
            [
                "director_key",
                "year_film",
                "director_prior_directing_nominations",
                "director_prior_directing_wins",
            ]
        ],
        on=["director_key", "year_film"],
        how="left",
    )

    film_directors["director_prior_directing_nominations"] = (
        pd.to_numeric(
            film_directors["director_prior_directing_nominations"], errors="coerce"
        ).fillna(0)
    )
    film_directors["director_prior_directing_wins"] = (
        pd.to_numeric(
            film_directors["director_prior_directing_wins"], errors="coerce"
        ).fillna(0)
    )

    director_features = (
        film_directors.groupby(["year_film", "film_key"], as_index=False)
        .agg(
            director_prior_directing_nominations=(
                "director_prior_directing_nominations",
                "sum",
            ),
            director_prior_directing_wins=(
                "director_prior_directing_wins",
                "sum",
            ),
        )
    )
    director_features["director_has_prior_directing_win"] = (
        director_features["director_prior_directing_wins"] > 0
    ).astype(int)
    return director_features


def merge_all(
    oscars_film: pd.DataFrame,
    movies_tbl: pd.DataFrame,
    movie_manual_overrides_tbl: pd.DataFrame,
    rt_tbl: pd.DataFrame,
    rt_recent_tbl: pd.DataFrame,
    festival_metacritic_tbl: pd.DataFrame,
    globes_tbl: pd.DataFrame,
    sag_tbl: pd.DataFrame,
    bafta_tbl: pd.DataFrame,
    pga_tbl: pd.DataFrame,
    dga_tbl: pd.DataFrame,
    critics_choice_tbl: pd.DataFrame,
    director_tbl: pd.DataFrame,
) -> pd.DataFrame:
    df = oscars_film.merge(movies_tbl, on="film_key", how="left")
    df = df.merge(movie_manual_overrides_tbl, on=["year_film", "film_key"], how="left")
    df["movie_rating"] = df["movie_rating_override"].combine_first(df["movie_rating"])
    df["movie_vote_count"] = df["movie_vote_count_override"].combine_first(df["movie_vote_count"])
    df = df.drop(columns=["movie_rating_override", "movie_vote_count_override"])
    df = df.merge(
        rt_tbl,
        left_on=["film_key", "year_film"],
        right_on=["film_key", "rt_release_year"],
        how="left",
    )
    df = df.merge(
        rt_recent_tbl,
        on=["year_film", "film_key"],
        how="left",
        suffixes=("", "_recent"),
    )
    df["rt_movie_title"] = df["film_recent"].combine_first(df["rt_movie_title"])
    df["tomatometer_rating"] = df["tomatometer_rating_recent"].combine_first(df["tomatometer_rating"])
    df["audience_rating"] = df["audience_rating_recent"].combine_first(df["audience_rating"])
    df["rt_release_month"] = df["rt_release_month_recent"].combine_first(df["rt_release_month"])
    df = df.drop(columns=["film_recent", "tomatometer_rating_recent", "audience_rating_recent", "rt_release_month_recent"])
    df = df.merge(festival_metacritic_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(globes_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(sag_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(bafta_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(pga_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(dga_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(critics_choice_tbl, on=["year_film", "film_key"], how="left")
    df = df.merge(director_tbl, on=["year_film", "film_key"], how="left")
    return df


def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    numeric_fill_zero = [
        "globe_nom_count",
        "globe_win_count",
        "golden_globe_win",
        "sag_nom_count",
        "sag_win_count",
        "sag_win",
        "bafta_nom_count",
        "bafta_win_count",
        "bafta_win",
        "pga_nom_count",
        "pga_win_count",
        "pga_win",
        "dga_nom_count",
        "dga_win_count",
        "dga_win",
        "critics_choice_nom_count",
        "critics_choice_win_count",
        "critics_choice_win",
        "tomatometer_rating",
        "tomatometer_count",
        "audience_rating",
        "audience_count",
        "runtime_in_minutes",
        "movie_rating",
        "movie_vote_count",
        "metacritic_score",
        "director_prior_directing_nominations",
        "director_prior_directing_wins",
        "cannes_flag",
        "venice_flag",
        "tiff_flag",
        "telluride_flag",
        "sundance_flag",
        "sxsw_flag",
    ]

    for col in numeric_fill_zero:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    rt_release_month = pd.to_numeric(df.get("rt_release_month"), errors="coerce")
    movie_release_month = pd.to_numeric(df.get("movie_release_month"), errors="coerce")
    df["release_month"] = rt_release_month.fillna(movie_release_month)
    df["movie_title"] = df["movie_title"].fillna(df["film"])
    df["movie_release_month"] = movie_release_month.fillna(df["release_month"])
    df["festival_presence_score"] = (
        df["cannes_flag"]
        + df["venice_flag"]
        + df["tiff_flag"]
        + df["telluride_flag"]
        + df["sundance_flag"]
        + df["sxsw_flag"]
    )
    df["major_festival_flag"] = (
        df[["cannes_flag", "venice_flag", "tiff_flag", "telluride_flag", "sundance_flag", "sxsw_flag"]]
        .sum(axis=1)
        .gt(0)
        .astype(int)
    )
    studio_name = df.get("studio_name")
    if studio_name is None:
        studio_name = pd.Series([pd.NA] * len(df), index=df.index)
    df["awards_distributor"] = df["movie_distributor"].combine_first(studio_name)
    distributor_text = df["awards_distributor"].astype(str)
    df["is_streaming_distributor"] = distributor_text.str.contains(
        r"netflix|apple|amazon|prime|hulu", case=False, na=False
    ).astype(int)
    df["is_prestige_distributor"] = distributor_text.str.contains(
        r"a24|searchlight|sony pictures classics|focus features|neon|ifc films|miramax|criterion|janus films",
        case=False,
        na=False,
    ).astype(int)
    df["is_major_studio_distributor"] = distributor_text.str.contains(
        r"warner|universal|paramount|disney|20th century|fox|sony pictures|columbia|mgm",
        case=False,
        na=False,
    ).astype(int)
    genre_text = df.get("movie_genres")
    if genre_text is None:
        genre_text = pd.Series([pd.NA] * len(df), index=df.index)
    df["is_drama_genre"] = genre_flag(genre_text, "Drama")
    df["is_history_genre"] = genre_flag(genre_text, "History")
    df["is_biography_genre"] = genre_flag(genre_text, "Biography")
    df["is_war_genre"] = genre_flag(genre_text, "War")
    df["is_music_genre"] = genre_flag(genre_text, "Music")
    df["is_romance_genre"] = genre_flag(genre_text, "Romance")
    df["prestige_genre_score"] = (
        df["is_drama_genre"] * 2
        + df["is_history_genre"] * 2
        + df["is_biography_genre"] * 2
        + df["is_war_genre"]
        + df["is_music_genre"]
        + df["is_romance_genre"]
    )

    df["momentum_score"] = (
        df["golden_globe_win"] * 5 +
        df["sag_win"] * 7 +
        df["bafta_win"] * 6
        + df["pga_win"] * 8
        + df["dga_win"] * 6
        + df["critics_choice_win"] * 4
        + df["globe_nom_count"]
        + df["sag_nom_count"]
        + df["bafta_nom_count"]
        + df["pga_nom_count"]
        + df["dga_nom_count"]
        + df["critics_choice_nom_count"]
    )

    df["high_nomination_flag"] = (df["oscar_nomination_count"] >= 8).astype(int)
    df["director_has_prior_directing_win"] = pd.to_numeric(
        df.get("director_has_prior_directing_win"), errors="coerce"
    ).fillna(0).astype(int)
    return df

def report_match_quality(df: pd.DataFrame):
    total_rows = len(df)

    checks = {
        "movie metadata matched": df["movie_title"].notna().sum() if "movie_title" in df.columns else 0,
        "rotten tomatoes matched": df["rt_movie_title"].notna().sum() if "rt_movie_title" in df.columns else 0,
        "golden globes matched": df["globe_nom_count"].fillna(0).gt(0).sum() if "globe_nom_count" in df.columns else 0,
        "sag matched": df["sag_nom_count"].fillna(0).gt(0).sum() if "sag_nom_count" in df.columns else 0,
        "bafta matched": df["bafta_nom_count"].fillna(0).gt(0).sum() if "bafta_nom_count" in df.columns else 0,
        "pga matched": df["pga_nom_count"].fillna(0).gt(0).sum() if "pga_nom_count" in df.columns else 0,
        "dga matched": df["dga_nom_count"].fillna(0).gt(0).sum() if "dga_nom_count" in df.columns else 0,
        "critics choice matched": df["critics_choice_nom_count"].fillna(0).gt(0).sum() if "critics_choice_nom_count" in df.columns else 0,
    }

    print("\nMatch Quality Report")
    print("-" * 40)
    print(f"Total Oscar film rows: {total_rows}")

    for label, matched in checks.items():
        pct = (matched / total_rows * 100) if total_rows else 0
        print(f"{label}: {matched} / {total_rows} ({pct:.1f}%)")

def save_data(df: pd.DataFrame):
    df.to_csv(FINAL_DATA_PATH, index=False)


def run_pipeline():
    print("Loading raw data...")
    (
        oscars,
        movies,
        movie_manual_overrides,
        globes,
        sag,
        bafta,
        pga,
        dga,
        critics_choice,
        globes_recent,
        sag_recent,
        bafta_recent,
        pga_recent,
        dga_recent,
        critics_choice_recent,
        rt_recent,
        festival_metacritic,
        rt_movies,
    ) = load_data()

    print("Standardizing columns...")
    (
        oscars,
        movies,
        movie_manual_overrides,
        globes,
        sag,
        bafta,
        pga,
        dga,
        critics_choice,
        globes_recent,
        sag_recent,
        bafta_recent,
        pga_recent,
        dga_recent,
        critics_choice_recent,
        rt_recent,
        festival_metacritic,
        rt_movies,
    ) = standardize_columns(
        oscars,
        movies,
        movie_manual_overrides,
        globes,
        sag,
        bafta,
        pga,
        dga,
        critics_choice,
        globes_recent,
        sag_recent,
        bafta_recent,
        pga_recent,
        dga_recent,
        critics_choice_recent,
        rt_recent,
        festival_metacritic,
        rt_movies,
    )

    print("Building Oscar target table...")
    oscars_film = build_oscar_film_table(oscars)

    print("Building movie metadata table...")
    movies_tbl = build_movies_table(movies)

    print("Building movie manual overrides table...")
    movie_manual_overrides_tbl = build_movie_manual_overrides_table(movie_manual_overrides)

    print("Building Rotten Tomatoes movie table...")
    rt_tbl = build_rt_movies_table(rt_movies)

    print("Building recent Rotten Tomatoes summary table...")
    rt_recent_tbl = build_recent_rt_summary_table(rt_recent)

    print("Building festival and Metacritic summary table...")
    festival_metacritic_tbl = build_festival_metacritic_table(festival_metacritic)

    print("Building Golden Globe features...")
    globes_tbl = build_globes_features(globes, globes_recent)

    print("Building SAG features...")
    sag_tbl = build_sag_features(sag, sag_recent)

    print("Building BAFTA features...")
    bafta_tbl = build_bafta_features(bafta, bafta_recent)

    print("Building PGA features...")
    pga_tbl = build_pga_features(pga, pga_recent)

    print("Building DGA features...")
    dga_tbl = build_dga_features(dga, dga_recent)

    print("Building Critics Choice features...")
    critics_choice_tbl = build_critics_choice_features(critics_choice, critics_choice_recent)

    print("Building director history features...")
    director_tbl = build_director_history_features(oscars, oscars_film, movies_tbl)

    print("Merging all tables...")
    final_df = merge_all(
        oscars_film,
        movies_tbl,
        movie_manual_overrides_tbl,
        rt_tbl,
        rt_recent_tbl,
        festival_metacritic_tbl,
        globes_tbl,
        sag_tbl,
        bafta_tbl,
        pga_tbl,
        dga_tbl,
        critics_choice_tbl,
        director_tbl,
    )

    print("Engineering features...")
    final_df = feature_engineering(final_df)

    report_match_quality(final_df)

    print("Saving final dataset...")
    save_data(final_df)

    print("Done.")
    print(final_df.head())


if __name__ == "__main__":
    run_pipeline()
