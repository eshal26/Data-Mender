"""
Stage 4 — Opens a real GitHub PR once a Fix Agent proposal has passed the
staging verifier (Stage 3). Requires a GITHUB_TOKEN with repo scope and
GITHUB_REPO (e.g. "your-username/self-healing-pipeline") in .env.

This is the human checkpoint: the agent opens the PR, but nothing merges
without manual approval. This script never pushes to main and never merges
anything itself.

Usage:
    python agents/github_integration/open_pr.py \
        --model-file transform/dbt_project/models/staging/stg_weather.sql \
        --category BAD_DATA \
        --summary "<Monitor Agent's summary>"
"""
import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from github import Github, GithubException

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")


def open_pr(
    branch: str,
    title: str,
    body: str,
    model_file_repo_path: str,
    fixed_sql: str,
    base_branch: str = "main",
) -> str:
    """
    Creates `branch` off `base_branch` (or reuses it if it already exists),
    commits `fixed_sql` to `model_file_repo_path` on that branch, and opens
    a PR from `branch` -> `base_branch` with `title`/`body`.

    Never merges — only opens the PR. Returns the PR URL.
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("Set GITHUB_TOKEN and GITHUB_REPO in .env first")

    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPO)

    base = repo.get_branch(base_branch)

    try:
        repo.get_branch(branch)
        branch_exists = True
    except GithubException:
        branch_exists = False

    if not branch_exists:
        repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base.commit.sha)

    try:
        existing = repo.get_contents(model_file_repo_path, ref=branch)
        repo.update_file(
            path=model_file_repo_path,
            message=f"fix({model_file_repo_path}): automated fix from Fix Agent",
            content=fixed_sql,
            sha=existing.sha,
            branch=branch,
        )
    except GithubException as e:
        raise RuntimeError(
            f"Could not update {model_file_repo_path} on branch {branch}: {e}"
        )

    existing_prs = repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch}")
    for pr in existing_prs:
        return pr.html_url

    pr = repo.create_pull(title=title, body=body, head=branch, base=base_branch)
    return pr.html_url


def build_pr_description(category: str, monitor_summary: str, fix_explanation: str, attempts: int) -> str:
    return f"""## Automated fix from the Self-Healing Pipeline agents

**Failure category (Monitor Agent):** `{category}`

**Monitor Agent diagnosis:**
{monitor_summary}

**Fix Agent explanation:**
{fix_explanation}

**Verification:** Passed `dbt run` + `dbt test` against an isolated staging schema after {attempts} attempt(s).

---
⚠️ **This PR was opened automatically. Nothing has been merged.** Please review the diff carefully before merging — automated verification checks that the pipeline builds and tests pass, but does not guarantee the fix is semantically correct (e.g. it cannot tell you whether dropped/nulled rows are acceptable for your use case).

_Generated {datetime.utcnow().isoformat()}Z_
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-file", required=True, help="Local path to the model file")
    parser.add_argument(
        "--model-file-repo-path",
        default=None,
        help="Path as it appears in the repo, if different from --model-file",
    )
    parser.add_argument("--category", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    repo_path = args.model_file_repo_path or args.model_file.replace("\\", "/")

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "verifier"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fix_agent"))
    from staging_runner import verify_with_retries  # noqa: E402
    from fix import propose_fix  # noqa: E402

    with open(args.model_file, encoding="utf-8") as f:
        original_sql = f.read()

    def _propose(previous_failure_log: str) -> str:
        summary = args.summary
        if previous_failure_log:
            summary += (
                "\n\nA previous fix attempt failed verification. Fix log:\n"
                f"{previous_failure_log[-3000:]}"
            )
        raw = propose_fix(args.category, summary, original_sql)
        if "```sql" in raw and raw.count("```") >= 2:
            return raw.split("```sql", 1)[1].split("```", 1)[0].strip()
        print(
            "WARNING: Fix Agent did not return a valid ```sql block. Raw response:\n"
            f"{raw[:500]}\n"
            "Falling back to the original SQL for this attempt.\n"
        )
        return original_sql

    success, final_sql, log, attempts = verify_with_retries(
        _propose,
        args.model_file,
        original_sql=original_sql,
    )

    if not success:
        print(f"Fix NOT verified after {attempts} attempt(s). Not opening a PR — escalate to a human.")
        sys.exit(1)

    branch_name = f"fix/auto-{args.category.lower()}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    pr_body = build_pr_description(args.category, args.summary, "(see verified SQL diff)", attempts)

    pr_url = open_pr(
        branch=branch_name,
        title=f"Automated fix: {args.category} in {os.path.basename(args.model_file)}",
        body=pr_body,
        model_file_repo_path=repo_path,
        fixed_sql=final_sql,
    )

    print(f"Opened PR: {pr_url}")
