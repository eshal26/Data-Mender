# Self-Healing Data Pipeline with Agentic Monitoring

A data pipeline that ingests, cleans, and transforms data on a schedule —
watched over by two local LLM agents instead of a human on-call engineer.

**Zero-cost stack**: Postgres, Prefect, dbt Core, Groq (free-tier hosted LLM
inference — swappable for local Ollama), GitHub Actions, Streamlit. No paid
APIs required.

## Architecture

```
Data Source (free API / Kaggle CSV)
        │  scheduled
        ▼
Prefect Flow: ingest → raw Postgres table
        │
        ▼
dbt: staging models → marts (clean tables) + dbt tests
        │
        │ pipeline succeeds / fails (+ dbt test results)
        ▼
MONITOR AGENT (Groq: llama-3.1-8b-instant, read-only)
  reads Prefect + dbt logs, classifies failure type
        │ failure detected
        ▼
FIX AGENT (Groq: llama-3.3-70b-versatile, write-to-branch only)
  proposes a patch (SQL fix / config change)
        │
        ▼
Staging re-run: apply fix to a staging copy, re-run pipeline + dbt tests
        │
   pass │        │ fail
        ▼        ▼
  Open PR on GitHub   Escalate (log + stop — no infinite loop)
  (human approves)
```

All components run in Docker. GitHub Actions lints + tests every PR
(including agent-proposed ones). Streamlit dashboard shows pipeline health
over time.

## Build stages

This repo is meant to be built incrementally — each stage is independently
demoable:

- [x] **Stage 0 — Plumbing.** Working pipeline, no AI. Prefect → Postgres →
      dbt models + tests. Includes a `--break` mode to deliberately inject
      failures (bad SQL, schema drift, null spikes) so later stages have
      real failures to classify.
- [ ] **Stage 1 — Read-only Monitor Agent.** Classifies + summarizes failures
      in plain English. No fixing yet.
- [ ] **Stage 2 — Fix Agent (human-applied).** Proposes a fix as a diff; you
      apply it manually to sanity-check proposals.
- [ ] **Stage 3 — Verification loop.** Fix auto-applied to staging, pipeline
      + tests re-run, pass/fail fed back to the agent. Capped retries.
- [ ] **Stage 4 — PR automation.** On a passing fix, agent opens a real
      GitHub PR with diff + reasoning. You merge manually.
- [ ] **Stage 5 — CI/CD + dashboard.** GitHub Actions on every PR, Streamlit
      dashboard.

This repo currently scaffolds Stage 0 end-to-end, plus stubs for Stages 1-4
so you can build into them without restructuring later.

## Free stack

| Component | Tool |
|---|---|
| Orchestration | Prefect (Docker, local) |
| Database | Postgres (Docker) |
| Transform | dbt Core |
| Agents (LLM) | Groq API free tier (Llama 3.1 8B for Monitor, Llama 3.3 70B for Fix) — swap to local Ollama via `LLM_PROVIDER=ollama` |
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

cd transform/dbt_project && dbt run && dbt test
```

## Repo structure

See inline comments in each subfolder. Key entry points:

- `orchestration/flows/daily_pipeline.py` — Prefect flow: fetch → load → dbt run/test
- `transform/dbt_project/` — dbt models + tests
- `agents/monitor_agent/monitor.py` — Stage 1 (stub, reads logs, calls Ollama)
- `agents/fix_agent/fix.py` — Stage 2 (stub)
- `agents/verifier/staging_runner.py` — Stage 3 (stub)
- `agents/github_integration/open_pr.py` — Stage 4 (stub)
- `dashboard/app.py` — Stage 5 (stub Streamlit page)

## Talking points (for CV / interviews)

- How infinite fix-retry loops are prevented (max retry count + escalation)
- How agent permissions are scoped (monitor = read-only, fix = write-branch
  only, never touches `main`/prod)
- Why "tests passed" isn't proof a fix is correct (e.g. a fix that silently
  drops rows would still pass) — and what additional check catches that
- Cost/latency tradeoffs of running LLM calls inside a monitoring loop
- What would change for a production version (tighter guardrails, human
  review before *any* staging re-run on high-risk tables)
