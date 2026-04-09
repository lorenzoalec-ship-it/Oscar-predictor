import argparse
from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
from typing import Optional

from build_site_data import run as build_site_data
from future_best_picture import run as run_future_best_picture
from pipeline import run_pipeline
from publish_github_pages import run as publish_github_pages
from pull_future_movies import output_path_for_year, run as pull_future_movies
from refresh_external_sources import run as refresh_external_sources


OUTPUT_DIR = Path("output")
RAW_DIR = Path("data/raw")
AGENT_UPDATES_DIR = Path("data/agent_updates")
REPORT_PATH_TEMPLATE = "output/agent_refresh_report_{year}.json"

MANAGED_UPDATE_FILES = [
    "golden_globe_recent_summary.csv",
    "sag_recent_summary.csv",
    "bafta_recent_summary.csv",
    "pga_recent_summary.csv",
    "dga_recent_summary.csv",
    "critics_choice_recent_summary.csv",
    "rotten_tomatoes_recent_summary.csv",
    "festival_metacritic_summary.csv",
    "future_contender_enrichment.csv",
]


def archive_existing_forecast(year: int):
    forecast_path = OUTPUT_DIR / f"future_best_picture_predictions_{year}.csv"
    if not forecast_path.exists():
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_dir = OUTPUT_DIR / "history" / str(year)
    history_dir.mkdir(parents=True, exist_ok=True)
    archive_path = history_dir / f"future_best_picture_predictions_{year}_{timestamp}.csv"
    shutil.copy2(forecast_path, archive_path)
    print(f"Archived previous forecast to {archive_path}")


def sync_agent_updates():
    synced = []
    missing = []

    AGENT_UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    for filename in MANAGED_UPDATE_FILES:
        source_path = AGENT_UPDATES_DIR / filename
        dest_path = RAW_DIR / filename
        if source_path.exists():
            shutil.copy2(source_path, dest_path)
            synced.append(str(dest_path))
            print(f"Synced agent update file: {source_path} -> {dest_path}")
        else:
            missing.append(str(source_path))

    return {"synced": synced, "missing": missing}


def write_refresh_report(year: int, report: dict):
    path = Path(REPORT_PATH_TEMPLATE.format(year=year))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(f"Wrote refresh report to {path}")


def run(
    year: int,
    skip_tmdb: bool = False,
    skip_source_refresh: bool = False,
    publish_pages: bool = False,
    pages_repo: Optional[str] = None,
    pages_branch: str = "main",
):
    started_at = datetime.now(timezone.utc).isoformat()
    external_refresh_report = {}
    if skip_source_refresh:
        print("Skipping external source refresh and using local update files as-is.")
    else:
        print("Refreshing awards, RT, festival, and Metacritic source files...")
        external_refresh_report = refresh_external_sources()

    sync_report = sync_agent_updates()

    print("Rebuilding historical model dataset...")
    run_pipeline()

    archive_existing_forecast(year)
    if skip_tmdb:
        print("Skipping TMDb pull and using the existing pool file.")
    else:
        print("Pulling latest TMDb future movie pool...")
        pull_future_movies(year)

    pool_path = Path(output_path_for_year(year))
    if not pool_path.exists():
        raise FileNotFoundError(
            f"Future movie pool not found at {pool_path}. "
            "Either remove --skip-tmdb or create the pool file first."
        )

    print("Scoring the future Best Picture race...")
    run_future_best_picture(year, pool_path)

    print("Rebuilding site data...")
    build_site_data()

    publish_report = {}
    if publish_pages:
        print("Publishing refreshed site data to GitHub Pages repo...")
        publish_report = publish_github_pages(repo=pages_repo or "lorenzoalec-ship-it/Oscar-predictor", branch=pages_branch)

    finished_at = datetime.now(timezone.utc).isoformat()
    report = {
        "year": year,
        "started_at": started_at,
        "finished_at": finished_at,
        "skip_tmdb": skip_tmdb,
        "skip_source_refresh": skip_source_refresh,
        "external_refresh_report": external_refresh_report,
        "synced_agent_updates": sync_report["synced"],
        "missing_agent_updates": sync_report["missing"],
        "tmdb_pool_path": str(pool_path),
        "forecast_output_path": str(OUTPUT_DIR / f"future_best_picture_predictions_{year}.csv"),
        "site_data_path": "site/data/site_data.json",
        "publish_pages": publish_pages,
        "publish_report": publish_report,
    }
    write_refresh_report(year, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the weekly Oscar agent loop: sync updates, rebuild historical data, refresh the future race, and rebuild the site."
    )
    parser.add_argument("--year", type=int, required=True, help="Eligibility year, for example 2026.")
    parser.add_argument(
        "--skip-tmdb",
        action="store_true",
        help="Use the existing TMDb pool file instead of pulling fresh data from TMDb.",
    )
    parser.add_argument(
        "--skip-source-refresh",
        action="store_true",
        help="Skip live refresh of awards, RT, festival, and Metacritic source files.",
    )
    parser.add_argument(
        "--publish-pages",
        action="store_true",
        help="Publish refreshed site data to the GitHub Pages repo using GITHUB_TOKEN.",
    )
    parser.add_argument(
        "--pages-repo",
        default="lorenzoalec-ship-it/Oscar-predictor",
        help="GitHub repository to publish Pages data into.",
    )
    parser.add_argument(
        "--pages-branch",
        default="main",
        help="Branch to publish Pages data into.",
    )
    args = parser.parse_args()
    run(
        args.year,
        skip_tmdb=args.skip_tmdb,
        skip_source_refresh=args.skip_source_refresh,
        publish_pages=args.publish_pages,
        pages_repo=args.pages_repo,
        pages_branch=args.pages_branch,
    )
