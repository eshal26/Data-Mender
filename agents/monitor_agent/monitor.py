"""
Stage 1 — Monitor Agent (read-only).

Reads the most recent failed run from `pipeline_runs` (written by
orchestration/flows/daily_pipeline.py), sends the log to a local Ollama
model, and asks it to classify the failure + summarize in plain English.

This agent NEVER writes to the pipeline or database — read-only by design.
Its output is just printed / can be piped to the Fix Agent in Stage 2.

Usage:
    python agents/monitor_agent/monitor.py
"""
import os

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

PG_DSN = (
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5433')} "
    f"dbname={os.getenv('POSTGRES_DB', 'shp')} "
    f"user={os.getenv('POSTGRES_USER', 'shp')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'shp')}"
)

# LLM_PROVIDER: "groq" (default, hosted, fast, free tier) or "ollama" (local, offline)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL_MONITOR = os.getenv("GROQ_MODEL_MONITOR", "openai/gpt-oss-20b")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

CLASSIFY_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "prompts", "classify.txt")
).read()


def get_latest_failure() -> dict | None:
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, run_at, injected_failure, log
        FROM pipeline_runs
        WHERE success = false
        ORDER BY run_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "run_at": row[1], "injected_failure": row[2], "log": row[3]}


def classify(log_text: str) -> str:
    prompt = CLASSIFY_PROMPT.format(log=log_text[-6000:])  # keep prompt bounded

    if LLM_PROVIDER == "ollama":
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    # Groq: OpenAI-compatible chat completions endpoint.
    if not GROQ_API_KEY:
        raise RuntimeError("Set GROQ_API_KEY in .env (or set LLM_PROVIDER=ollama)")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": GROQ_MODEL_MONITOR,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def main():
    failure = get_latest_failure()
    if not failure:
        print("No failed runs found. Nothing to classify.")
        return

    print(f"Classifying failed run #{failure['id']} from {failure['run_at']}...")
    classification = classify(failure["log"])
    print("\n--- Monitor Agent classification ---")
    print(classification)


if __name__ == "__main__":
    main()
