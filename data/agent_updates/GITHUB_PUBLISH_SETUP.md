Set a GitHub personal access token in your shell before using `--publish-pages`.

Example:

```bash
export GITHUB_TOKEN="your_github_pat_here"
```

Then run:

```bash
./venv/bin/python src/update_future_best_picture_race.py --year 2026 --publish-pages
```

Recommended token permissions:

- `repo` for a private repo
- `public_repo` for a public repo

The default publish target is:

- `lorenzoalec-ship-it/Oscar-predictor`

You can override it with:

```bash
./venv/bin/python src/update_future_best_picture_race.py --year 2026 --publish-pages --pages-repo owner/name
```
