# DataMender

A self-healing data pipeline that ingests, cleans, and transforms data on a
schedule — watched over by two LLM agents instead of a human on-call
engineer. When the pipeline breaks, a Monitor Agent diagnoses why, a Fix
Agent proposes a patch, an automated verifier tests that patch in an
isolated schema (retrying on failure), and — only once a fix is proven safe
— a GitHub pull request is opened for human review. Nothing merges
automatically.

**Zero-cost stack**: Postgres, Prefect, dbt Core, Groq (free-tier hosted LLM
inference, swappable for local Ollama), GitHub Actions, Streamlit.

## Architecture

    Data Source (free API)
            │  scheduled
            ▼
    Prefect: ingest → raw Postgres table
            ▼
    dbt: staging models → marts + tests
            │  pipeline succeeds / fails
            ▼
    MONITOR AGENT (Groq, read-only) — classifies the failure
            ▼
    FIX AGENT (Groq, temperature=0, branch-only) — proposes a patch
            ▼
    Staging verifier: apply fix to `staging_verify`, run
    dbt run + dbt test + row-retention check, retry (max 3)
            │
       pass │        │ fail after 3 attempts
            ▼        ▼
      Open GitHub PR    Escalate to a human
      (human approves)

All components run in Docker. GitHub Actions lints + tests every PR.
Streamlit dashboard shows pipeline health over time.

## Status

All 5 stages are implemented and have been run end-to-end successfully,
including an autonomous run that opened a real GitHub PR after the Fix
Agent produced a working fix and the verifier confirmed it. See Findings
for two distinct "fix looks correct but isn't" cases the verifier caught.

- [x] **Stage 0 — Plumbing.** Prefect → Postgres → dbt, with
      `--break {bad_column|schema_drift|null_spike}` to inject failures.
- [x] **Stage 1 — Monitor Agent.** Read-only. Classifies the latest failure
      (`BAD_DATA`, `SCHEMA_DRIFT`, `TEST_FAILURE`, `UNKNOWN`) with a summary.
- [x] **Stage 2 — Fix Agent.** Proposes a corrected model file as a diff.
- [x] **Stage 3 — Staging verifier.** Applies the fix to an isolated
      `staging_verify` schema, runs `dbt run` + `dbt test` + a
      row-retention check, retries up to 3 times before escalating.
- [x] **Stage 4 — PR automation.** Opens a GitHub PR on a verified fix
      (needs `GITHUB_TOKEN` + `GITHUB_REPO`). Never merges automatically.
- [ ] **Stage 5 — CI/CD + dashboard.** Scaffolded and runnable, not polished.

## Findings (real issues hit while building this)

- **Native vs. Docker Postgres port conflict.** A Windows-native
  `postgres.exe` silently shared port 5432 with Docker's container, routing
  connections to the wrong server. Fixed by moving Docker to port 5433.
- **Fix passes build, fails tests.** An early fix cast bad values to `NULL`
  instead of dropping the row — `dbt run` passed, `dbt test`'s `not_null`
  check correctly caught it.
- **Fix passes tests, drops all data.** A later fix passed both `dbt run`
  and `dbt test` but had filtered out 100% of rows — an empty table
  trivially satisfies `not_null`. Only caught after adding a dedicated
  row-retention check comparing raw vs. staging row counts. The strongest
  concrete case for why "tests passed" isn't sufficient on its own.
- **LLM dialect/schema hallucination.** The Fix Agent invented SQL Server
  syntax (`TRY_CAST`), invalid Jinja comments (`{{-- --}}`), and fabricated
  table/column names. Reduced (not eliminated) via `temperature=0` and an
  explicit "copy identifiers verbatim" prompt rule.
- **Unsafe LLM output handling.** When the Fix Agent returned prose instead
  of a ```sql``` block, the original code wrote that prose into the `.sql`
  file. Fixed by falling back to the unmodified original SQL when no valid
  code block is found.
- **Model deprecation mid-project.** `llama-3.1-8b-instant` /
  `llama-3.3-70b-versatile` were shut down on Groq's free tier; swapped to
  `openai/gpt-oss-20b` / `openai/gpt-oss-120b`.
- **Windows encoding mismatches.** LLM output often contains Unicode
  punctuation that Windows' default `cp1252` encoding can't write, and dbt
  can't parse. Fixed by forcing `encoding="utf-8"` everywhere.
- **Non-determinism at temperature 0.** The same failure and prompt
  produced different outcomes across runs — worth stating plainly rather
  than claiming full determinism.

## Free stack

| Component | Tool |
|---|---|
| Orchestration | Prefect (Docker) |
| Database | Postgres (Docker) |
| Transform | dbt Core |
| Agents | Groq free tier (`gpt-oss-20b` Monitor, `gpt-oss-120b` Fix, temp=0) — or local Ollama via `LLM_PROVIDER=ollama` |
| CI | GitHub Actions |
| Dashboard | Streamlit |
| Data source | Open-Meteo weather API (free, no key) |

## Setup

**1. Prerequisites:** Python 3.11+, Docker Desktop, a free Groq key
(console.groq.com/keys), and optionally a GitHub token with `repo` scope
(github.com/settings/tokens) for Stage 4.

**2. Configure:**
```bash
cp .env.example .env
# set GROQ_API_KEY, and optionally GITHUB_TOKEN + GITHUB_REPO
```

**3. Start Postgres:**
```bash
docker compose up -d postgres
```
> Windows: if a native Postgres service already runs on 5432, it can
> silently conflict with Docker's container. This project defaults Docker
> to port **5433** to avoid that — check `netstat -ano | findstr :5432`
> if you still see auth errors.

**4. Install dependencies:**
```bash
pip install -r requirements.txt
```
> Windows: versions are pinned to ones with prebuilt wheels for Python 3.13
> (`dbt-postgres==1.8.2`, `psycopg2-binary==2.9.10`, `pandas==2.2.3`,
> `griffe==0.47.0`, `pydantic==2.9.2`). A build error asking for a C++
> compiler usually means a stale pin, not a missing compiler.

**5. Run the pipeline:**
```bash
python orchestration/flows/daily_pipeline.py
python orchestration/flows/daily_pipeline.py --break bad_column   # inject a failure
cd transform/dbt_project && dbt run && dbt test
```
> Windows: `dbt` reads `profiles.yml` via real shell env vars, not `.env`.
> If `dbt` can't connect (but the Python pipeline can), set them manually:
> `$env:POSTGRES_HOST="127.0.0.1"`, `$env:POSTGRES_PORT="5433"`,
> `$env:POSTGRES_USER="shp"`, `$env:POSTGRES_PASSWORD="shp"`,
> `$env:POSTGRES_DB="shp"`.

**6. Run the agents:**
```bash
python agents/monitor_agent/monitor.py
python agents/fix_agent/fix.py --category BAD_DATA --summary "<summary>" --model-file transform/dbt_project/models/staging/stg_weather.sql
```

**7. Run the full automated loop:**
```bash
python orchestration/flows/daily_pipeline.py --break bad_column
python agents/verifier/staging_runner.py --model-file transform/dbt_project/models/staging/stg_weather.sql --category BAD_DATA --summary "temperature_c contains non-numeric text values causing a cast failure"

# same, but opens a PR on success (needs GITHUB_TOKEN)
python agents/github_integration/open_pr.py --model-file transform/dbt_project/models/staging/stg_weather.sql --category BAD_DATA --summary "temperature_c contains non-numeric text values causing a cast failure"
```

**8. Run tests:**
```bash
pytest tests/ -v
```

## Repo structure

    orchestration/flows/daily_pipeline.py   # Prefect: fetch → load → dbt
    transform/dbt_project/                  # dbt models, sources, tests
    agents/monitor_agent/monitor.py         # Stage 1: failure classifier
    agents/fix_agent/fix.py                 # Stage 2: proposes a fix
    agents/verifier/staging_runner.py       # Stage 3: verify + retry + escalate
    agents/github_integration/open_pr.py    # Stage 4: opens a PR on success
    dashboard/app.py                        # Stage 5: Streamlit health view
    .github/workflows/ci.yml                # lint + test on every PR
    tests/                                  # pytest suite