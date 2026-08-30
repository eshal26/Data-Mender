
All components run in Docker. GitHub Actions lints + tests every PR
(including agent-proposed ones). Streamlit dashboard shows pipeline health
over time.

## Build stages

- [x] **Stage 0 — Plumbing.** Working pipeline, no AI. Prefect → Postgres →
      dbt models + tests. Includes a `--break` mode to deliberately inject
      failures (bad SQL, schema drift, null spikes) so later stages have
      real failures to classify.
- [x] **Stage 1 — Read-only Monitor Agent.** Classifies + summarizes failures
      in plain English. No fixing yet. Confirmed working: correctly
      classified an injected type-mismatch failure as `BAD_DATA` with an
      accurate root-cause summary.
- [x] **Stage 2 — Fix Agent.** Proposes a fix as a diff. Confirmed working,
      with real caveats documented below under Findings.
- [x] **Stage 3 — Verification loop.** Fix auto-applied to a `staging_verify`
      schema, `dbt run` + `dbt test` re-run, pass/fail fed back to the Fix
      Agent for a retry (max 3 attempts) before escalating. A fix only
      counts as verified if BOTH `dbt run` and `dbt test` pass. Mechanism
      confirmed working (correctly escalates instead of opening a bad PR);
      fix quality from the LLM is still inconsistent — see Findings.
- [x] **Stage 4 — PR automation.** Reuses the Stage 3 verify loop; on a
      passing fix, opens a real GitHub PR with the diff and Monitor/Fix
      Agent reasoning attached. Requires `GITHUB_TOKEN` + `GITHUB_REPO` in
      `.env`. Never merges automatically.
- [ ] **Stage 5 — CI/CD + dashboard.** GitHub Actions workflow and Streamlit
      dashboard are scaffolded; CI dependency versions were fixed to match
      what actually works locally (see `requirements.txt`).

## Findings (real issues hit while building this)

These came up during actual development and are worth keeping — they're
better interview material than a project that "just worked":

- **Native Postgres vs. Docker Postgres port conflict.** A Windows-native
  `postgres.exe` service was silently listening on the same port (5432) as
  the Docker container, so connections were routed to the wrong server with
  the wrong credentials. Fixed by moving Docker's Postgres to port 5433.
- **A fix can build successfully but still be wrong.** An early Fix Agent
  proposal cast bad values to `NULL` instead of dropping the row — `dbt run`
  passed, but `dbt test`'s `not_null` constraint caught it. This is the
  concrete case for why Stage 3 checks BOTH `dbt run` and `dbt test`, not
  just one.
- **LLM dialect/schema hallucination.** The Fix Agent (on a 70B model)
  repeatedly invented SQL Server syntax (`TRY_CAST`, not valid in Postgres),
  invalid Jinja comment syntax (`{{-- --}}` instead of `{# #}`), and
  fabricated table/column names not present in the actual file (e.g.
  `raw_table`, `humidity`, `wind_speed` instead of the real schema). Tighter,
  more explicit prompt constraints (dialect lock, "copy identifiers verbatim,
  do not invent them") measurably reduced but did not eliminate this.
- **Unsafe extraction of the LLM's response.** When the Fix Agent didn't
  return a clean ` ```sql ` code block (e.g. it asked a clarifying question
  instead), the original extraction logic fell back to treating the raw
  prose as SQL, writing English text into a `.sql` file and producing
  confusing downstream errors. Fixed by falling back to the original,
  unmodified SQL when no valid code block is found, so a bad LLM response
  never corrupts the model file.
- **Model deprecation.** `llama-3.1-8b-instant` and `llama-3.3-70b-versatile`
  were shut down on Groq's free tier partway through development; swapped
  to `openai/gpt-oss-20b` / `openai/gpt-oss-120b`.
- **Windows encoding mismatches.** LLM-generated text often includes Unicode
  punctuation (em-dashes, non-breaking hyphens) that Windows' default
  `cp1252` encoding can't write to disk. Fixed by forcing `encoding="utf-8"`
  on every file read/write and subprocess call in the verifier.

## Free stack

| Component | Tool |
|---|---|
| Orchestration | Prefect (Docker, local) |
| Database | Postgres (Docker) |
| Transform | dbt Core |
| Agents (LLM) | Groq API free tier (`openai/gpt-oss-20b` for Monitor, `openai/gpt-oss-120b` for Fix) — swap to local Ollama via `LLM_PROVIDER=ollama` |
| Version control / CI | GitHub + GitHub Actions |
| Containers | Docker Desktop |
| Dashboard | Streamlit |
| Data source | Free public API (default: Open-Meteo weather API, no key needed) |

## Quickstart

```bash
cp .env.example .env
# add your free Groq key (console.groq.com/keys, no credit card) to .env as GROQ_API_KEY
docker compose up -d postgres

# run the pipeline once, normally
python orchestration/flows/daily_pipeline.py

# run it in "break" mode to inject a failure on purpose
python orchestration/flows/daily_pipeline.py --break bad_column

cd transform/dbt_project
dbt run
dbt test
```

To exercise the full agent chain:
```bash
python orchestration/flows/daily_pipeline.py --break bad_column
python agents/monitor_agent/monitor.py
python agents/verifier/staging_runner.py --model-file transform/dbt_project/models/staging/stg_weather.sql --category BAD_DATA --summary "<paste Monitor Agent's summary>"
```

To also open a PR on a verified fix, add `GITHUB_TOKEN` (a Personal Access
Token with `repo` scope, from github.com/settings/tokens) and `GITHUB_REPO`
to `.env`, then run `agents/github_integration/open_pr.py` with the same
arguments as `staging_runner.py`.

## Repo structure

- `orchestration/flows/daily_pipeline.py` — Prefect flow: fetch → load → dbt run/test
- `transform/dbt_project/` — dbt models + tests
- `agents/monitor_agent/monitor.py` — Stage 1: read-only failure classifier
- `agents/fix_agent/fix.py` — Stage 2: proposes a fix
- `agents/verifier/staging_runner.py` — Stage 3: verifies a fix in an isolated schema, retries, escalates
- `agents/github_integration/open_pr.py` — Stage 4: opens a PR on a verified fix
- `dashboard/app.py` — Stage 5: Streamlit health dashboard

## Talking points (for CV / interviews)

- How infinite fix-retry loops are prevented (max retry count + escalation)
- How agent permissions are scoped (monitor = read-only, fix = write-branch
  only, never touches `main`/prod)
- Why "tests passed" isn't proof a fix is correct — concrete example: a fix
  that converts bad values to `NULL` passes `dbt run` but fails a `not_null`
  test
- LLM reliability issues in structured code generation: dialect
  hallucination, schema hallucination, and unsafe assumptions about output
  format — and the defensive coding needed around an LLM's output before
  trusting it (never write an unvalidated LLM response straight to a file)
- Cost/latency tradeoffs of running LLM calls inside a monitoring loop
- What would change for a production version (tighter guardrails, human
  review before *any* staging re-run on high-risk tables, possibly a more
  constrained/deterministic model or a diff-based rather than full-file-
  regeneration fix format)