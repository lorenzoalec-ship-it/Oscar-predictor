# GitHub Pages Setup

This repo is configured to deploy the `site/` folder to GitHub Pages with the workflow at:

- `.github/workflows/deploy-pages.yml`

## One-time setup

1. Create a new GitHub repository.
2. Initialize Git in this project folder if needed:

```bash
cd /Users/aleclorenzo/Documents/oscar-predictor
git init
git branch -M main
git add .
git commit -m "Initial Oscar predictor site"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

3. In GitHub:
- open the repository
- go to `Settings` -> `Pages`
- set `Source` to `GitHub Actions`

After that, every push to `main` will publish the contents of `site/`.

## Public URL

For a normal project repo, the URL will usually be:

```text
https://YOUR_USERNAME.github.io/YOUR_REPO/
```

## Updating the live site

Before pushing, rebuild the local site assets:

```bash
./venv/bin/python src/update_future_best_picture_race.py --year 2026
```

Then commit and push the updated files so GitHub Pages redeploys.
