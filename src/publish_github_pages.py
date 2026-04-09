import argparse
import base64
import json
import os
from pathlib import Path
from typing import List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_REPO = "lorenzoalec-ship-it/Oscar-predictor"
DEFAULT_BRANCH = "main"
ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
DEFAULT_PATHS = [
    SITE_DIR / "data" / "site_data.json",
    SITE_DIR / "data" / "site_data.js",
]


_REQUEST_TIMEOUT = 20


def github_request(url: str, token: str, method: str = "GET", data: Optional[dict] = None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "oscar-predictor-publisher",
    }
    payload = None if data is None else json.dumps(data).encode("utf-8")
    request = Request(url, data=payload, headers=headers, method=method)
    with urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def validate_token(token: str) -> None:
    try:
        github_request("https://api.github.com/user", token)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise EnvironmentError(
                f"GITHUB_TOKEN is invalid or lacks required permissions (HTTP {exc.code})."
            ) from exc
        raise


def get_remote_sha(repo: str, branch: str, repo_path: str, token: str):
    url = f"https://api.github.com/repos/{repo}/contents/{repo_path}?ref={branch}"
    try:
        response = github_request(url, token)
        return response.get("sha")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def upload_file(repo: str, branch: str, local_path: Path, repo_path: str, token: str, message: str):
    content = local_path.read_text(encoding="utf-8")
    sha = get_remote_sha(repo, branch, repo_path, token)
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    url = f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    response = github_request(url, token, method="PUT", data=payload)
    return {
        "path": repo_path,
        "sha": response.get("content", {}).get("sha"),
        "created": sha is None,
    }


def infer_repo_path(local_path: Path) -> str:
    return str(local_path.relative_to(ROOT)).replace(os.sep, "/")


def run(
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
    token: Optional[str] = None,
    paths: Optional[List[Path]] = None,
    commit_message: Optional[str] = None,
):
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError(
            "Missing GITHUB_TOKEN. Export a GitHub personal access token before publishing."
        )
    validate_token(token)

    paths = paths or DEFAULT_PATHS
    message = commit_message or "Refresh Oscar forecast site data"

    published = []
    for local_path in paths:
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Cannot publish missing file: {local_path}")
        repo_path = infer_repo_path(local_path)
        published.append(upload_file(repo, branch, local_path, repo_path, token, message))

    return {
        "repo": repo,
        "branch": branch,
        "published": published,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish site data files to a GitHub Pages repo.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repository in owner/name form.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Target branch.")
    parser.add_argument(
        "--message",
        default="Refresh Oscar forecast site data",
        help="Commit message for the published content.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional specific files to publish. Defaults to site/data JSON and JS payloads.",
    )
    args = parser.parse_args()

    path_values = [Path(path) for path in args.paths] if args.paths else None
    report = run(repo=args.repo, branch=args.branch, paths=path_values, commit_message=args.message)
    print(json.dumps(report, indent=2))
