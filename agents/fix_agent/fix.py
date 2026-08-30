"""
Stage 2 — Fix Agent (write-to-branch only, never touches main/prod directly).

Takes the Monitor Agent's classification + summary and proposes a concrete
fix as a diff against a dbt model file. In Stage 2 this is applied manually
by you to sanity-check proposals; from Stage 3 onward it feeds into the
staging verification loop (agents/verifier/staging_runner.py).

Usage:
    python agents/fix_agent/fix.py --category BAD_DATA \\
        --summary "temperature_c contains the string 'not_a_number'..." \\
        --model-file transform/dbt_project/models/staging/stg_weather.sql
"""
import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()

# LLM_PROVIDER: "groq" (default, hosted, fast, free tier) or "ollama" (local, offline)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Fix proposals need stronger reasoning than classification, so this agent
# defaults to the larger model.
GROQ_MODEL_FIX = os.getenv("GROQ_MODEL_FIX", "llama-3.3-70b-versatile")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

PROPOSE_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "prompts", "propose_fix.txt")
).read()


def propose_fix(category: str, summary: str, model_sql: str) -> str:
    prompt = PROPOSE_PROMPT.format(category=category, summary=summary, model_sql=model_sql)

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
            "model": GROQ_MODEL_FIX,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--model-file", required=True, help="Path to the dbt model .sql file to fix")
    args = parser.parse_args()

    with open(args.model_file) as f:
        model_sql = f.read()

    proposal = propose_fix(args.category, args.summary, model_sql)
    print("\n--- Fix Agent proposal ---")
    print(proposal)
    print(
        "\n(Stage 2: apply this manually and re-run `dbt run && dbt test` to "
        "check it. Stage 3 automates this via agents/verifier/staging_runner.py)"
    )


if __name__ == "__main__":
    main()
