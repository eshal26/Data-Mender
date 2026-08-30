"""
Stage 3 — Staging verifier.

Applies a Fix Agent proposal to a throwaway copy of the affected dbt model,
re-runs `dbt run` + `dbt test` against a separate staging schema
(`staging_verify`, configured in profiles.yml), and reports pass/fail. This
is the safety gate: nothing from the Fix Agent reaches a PR (let alone
main) without passing here first.

Critically, "passing" means BOTH `dbt run` succeeds AND `dbt test` passes —
a fix that runs cleanly but fails a data-quality test (e.g. converts bad
values to NULL when a not_null test exists) is NOT considered verified.
This is exactly the gap discovered by hand while building this project:
a Fix Agent proposal built successfully but silently nulled out every row
of a not_null column, which only `dbt test` caught.

Also enforces a max retry count so the Monitor -> Fix -> Verify loop can't
spin forever on an unfixable failure — after MAX_ATTEMPTS, escalate to a
human instead of retrying again.

Usage:
    python agents/verifier/staging_runner.py --model-file <path> --category BAD_DATA \
        --summary "<Monitor Agent's summary>"
"""
import argparse
import os
import shutil
import subprocess

MAX_ATTEMPTS = 3

DBT_PROJECT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "transform", "dbt_project"
)


def _run_dbt(command: list[str]) -> tuple[bool, str]:
    """Runs a dbt command against the staging_verify target. Returns (success, log)."""
    result = subprocess.run(
        command + ["--target", "staging_verify"],
        cwd=DBT_PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log = f"$ {' '.join(command)} --target staging_verify\n{result.stdout}\n{result.stderr}"
    return result.returncode == 0, log


def apply_fix_to_staging(fixed_sql: str, model_file: str) -> str:
    """
    Backs up the current model file, then overwrites it with the proposed
    fix. Returns the path to the backup so the caller can restore it
    afterward — this function never leaves the real model file in a
    modified state beyond the caller's control.

    Always writes/reads as UTF-8 explicitly — Windows' default encoding
    (cp1252) can't represent characters like em-dashes or non-breaking
    hyphens that LLM-generated text often includes, and dbt itself expects
    UTF-8 source files.
    """
    backup_path = model_file + ".bak"
    shutil.copyfile(model_file, backup_path)
    with open(model_file, "w", encoding="utf-8") as f:
        f.write(fixed_sql)
    return backup_path


def restore_model(model_file: str, backup_path: str) -> None:
    shutil.move(backup_path, model_file)


def verify_fix(fixed_sql: str, model_file: str) -> tuple[bool, str]:
    """
    Applies `fixed_sql` to `model_file`, runs `dbt run` + `dbt test` against
    the staging_verify schema, then restores the original file regardless
    of outcome. Returns (success, combined_log). success is True only if
    BOTH dbt run and dbt test pass.
    """
    backup_path = apply_fix_to_staging(fixed_sql, model_file)
    try:
        run_ok, run_log = _run_dbt(["dbt", "run"])
        if not run_ok:
            return False, run_log

        test_ok, test_log = _run_dbt(["dbt", "test"])
        combined_log = run_log + "\n\n" + test_log
        return test_ok, combined_log
    finally:
        restore_model(model_file, backup_path)


def verify_with_retries(propose_fix_fn, model_file: str, max_attempts: int = MAX_ATTEMPTS):
    """
    Calls `propose_fix_fn(previous_failure_log)` to get a new fix proposal,
    verifies it, and retries with the failure fed back to the Fix Agent if
    it doesn't pass — up to `max_attempts` times.

    `propose_fix_fn` should accept a single argument: the log from the
    previous failed verification attempt (empty string on the first try),
    and return the proposed SQL as a string.

    Returns (success: bool, final_sql_or_None, log: str, attempts: int).
    On exhausting attempts without a passing fix, success is False and the
    caller should escalate to a human rather than retry again.
    """
    previous_failure_log = ""
    for attempt in range(1, max_attempts + 1):
        proposed_sql = propose_fix_fn(previous_failure_log)
        print(f"\n{'='*60}\nAttempt {attempt}/{max_attempts} — proposed SQL:\n{'='*60}")
        print(proposed_sql)
        print(f"{'='*60}\nVerifying against staging_verify...\n")

        success, log = verify_fix(proposed_sql, model_file)

        if success:
            print(f"Attempt {attempt} PASSED verification.")
            return True, proposed_sql, log, attempt

        print(f"Attempt {attempt} FAILED verification. Log:\n{log[-2000:]}\n")
        previous_failure_log = log

    return False, None, previous_failure_log, max_attempts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-file", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    # Wire up the Fix Agent as the propose_fix_fn, feeding back the previous
    # verification failure log (if any) so retries have more context than
    # the first attempt.
    import sys

    sys.path.insert(
        0, os.path.join(os.path.dirname(__file__), "..", "fix_agent")
    )
    from fix import propose_fix  # noqa: E402

    with open(args.model_file, encoding="utf-8") as f:
        original_sql = f.read()

    def _propose(previous_failure_log: str) -> str:
        summary = args.summary
        if previous_failure_log:
            summary += (
                "\n\nA previous fix attempt was verified against a staging "
                "schema and failed. Here is the dbt run/test output from "
                "that attempt — fix the issue it reveals:\n"
                f"{previous_failure_log[-3000:]}"
            )
        raw = propose_fix(args.category, summary, original_sql)
        # Extract the SQL block from the Fix Agent's formatted response.
        if "```sql" in raw:
            return raw.split("```sql", 1)[1].split("```", 1)[0].strip()
        return raw

    success, final_sql, log, attempts = verify_with_retries(_propose, args.model_file)

    if success:
        print(f"Fix verified after {attempts} attempt(s). Ready to open a PR (Stage 4).")
        print("\n--- Verified fix ---")
        print(final_sql)
    else:
        print(f"Fix NOT verified after {attempts} attempt(s). Escalating to a human.")
        print("\n--- Last failure log ---")
        print(log[-3000:])