Drop refreshed CSVs into this folder before running the weekly agent loop.

Supported filenames:
- golden_globe_recent_summary.csv
- sag_recent_summary.csv
- bafta_recent_summary.csv
- rotten_tomatoes_recent_summary.csv
- festival_metacritic_summary.csv
- future_contender_enrichment.csv

The weekly agent command will now also try to auto-refresh these files from the
source manifests in this folder:
- awards_wikipedia_manifest.json
- film_wikipedia_manifest.csv

That live refresh writes fresh CSVs into this folder first, then copies them into
data/raw/ before rebuilding the historical dataset, rescoring the future race,
and regenerating the site.

Example:
./venv/bin/python src/update_future_best_picture_race.py --year 2026 --skip-tmdb

Skip external source refresh if you only want to reuse the latest local CSVs:
./venv/bin/python src/update_future_best_picture_race.py --year 2026 --skip-source-refresh
