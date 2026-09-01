"""
Stage 0 pipeline — no AI involved yet.

Fetches data from a free public API (Open-Meteo weather forecast, no key
needed), loads it into Postgres, then runs dbt to build + test staging/mart
models.

Run normally:
    python orchestration/flows/daily_pipeline.py

Run with a deliberately injected failure (for Monitor Agent development in
later stages):
    python orchestration/flows/daily_pipeline.py --break bad_column
    python orchestration/flows/daily_pipeline.py --break schema_drift
    python orchestration/flows/daily_pipeline.py --break null_spike
"""
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from prefect import flow, task, get_run_logger
from prefect.exceptions import MissingContextError

load_dotenv()

PG_DSN = (
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5433')} "
    f"dbname={os.getenv('POSTGRES_DB', 'shp')} "
    f"user={os.getenv('POSTGRES_USER', 'shp')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'shp')}"
)

DATA_SOURCE_URL = os.getenv(
    "DATA_SOURCE_URL",
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=24.86&longitude=67.01"
    "&hourly=temperature_2m,relative_humidity_2m,precipitation",
)

DBT_PROJECT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "transform", "dbt_project")


def get_logger():
    try:
        return get_run_logger()
    except MissingContextError:
        return logging.getLogger(__name__)


@task(retries=0)
def fetch_data(inject: str | None) -> dict:
    logger = get_logger()
    resp = requests.get(DATA_SOURCE_URL, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    logger.info("Fetched %d hourly records", len(payload.get("hourly", {}).get("time", [])))

    if inject == "null_spike":
        # Simulate an upstream data quality issue: wipe out most humidity readings.
        hourly = payload.get("hourly", {})
        if "relative_humidity_2m" in hourly:
            hourly["relative_humidity_2m"] = [None] * len(hourly["relative_humidity_2m"])
        logger.warning("Injected failure: null_spike (relative_humidity_2m nulled out)")

    return payload


@task(retries=0)
def load_raw(payload: dict, inject: str | None) -> int:
    import psycopg2

    logger = get_logger()
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    humidity = hourly.get("relative_humidity_2m", [])
    precip = hourly.get("precipitation", [])

    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_weather (
            ts TIMESTAMP,
            temperature_c TEXT,
            humidity_pct DOUBLE PRECISION,
            precipitation_mm DOUBLE PRECISION,
            loaded_at TIMESTAMP DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'raw_weather'
              AND column_name = 'temp_celsius'
        )
        """
    )
    has_temp_celsius = cur.fetchone()[0]
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'raw_weather'
              AND column_name = 'temperature_c'
        )
        """
    )
    has_temperature_c = cur.fetchone()[0]
    if has_temp_celsius and not has_temperature_c:
        cur.execute("ALTER TABLE raw_weather RENAME COLUMN temp_celsius TO temperature_c")
        logger.info("Restored raw_weather.temperature_c after prior schema_drift run")

    if inject == "schema_drift":
        # Simulate an upstream API/schema change: rename a column dbt expects.
        cur.execute("ALTER TABLE raw_weather RENAME COLUMN temperature_c TO temp_celsius")
        logger.warning("Injected failure: schema_drift (temperature_c -> temp_celsius)")
        conn.commit()
        cur.close()
        conn.close()
        return 0

    cur.execute("TRUNCATE raw_weather")

    rows = list(zip(times, temps, humidity, precip))
    for idx, (ts, t, h, p) in enumerate(rows):
        if inject == "bad_column" and idx == 0:
            # Simulate one bad upstream value: text in a numeric column.
            cur.execute(
                "INSERT INTO raw_weather (ts, temperature_c, humidity_pct, precipitation_mm) "
                "VALUES (%s, %s, %s, %s)",
                (ts, "not_a_number", h, p),
            )
        else:
            cur.execute(
                "INSERT INTO raw_weather (ts, temperature_c, humidity_pct, precipitation_mm) "
                "VALUES (%s, %s, %s, %s)",
                (ts, t, h, p),
            )

    conn.commit()
    cur.close()
    conn.close()
    logger.info("Loaded %d rows into raw_weather", len(rows))
    return len(rows)


@task(retries=0)
def run_dbt() -> tuple[bool, str]:
    """Runs `dbt run` then `dbt test`. Returns (success, combined_log_text)."""
    logger = get_logger()
    log_chunks = []
    success = True

    for cmd in (["dbt", "run"], ["dbt", "test"]):
        result = subprocess.run(
            cmd, cwd=DBT_PROJECT_DIR, capture_output=True, text=True
        )
        log_chunks.append(f"$ {' '.join(cmd)}\n{result.stdout}\n{result.stderr}")
        logger.info(result.stdout)
        if result.returncode != 0:
            logger.error("Command failed: %s", " ".join(cmd))
            success = False
            break

    return success, "\n\n".join(log_chunks)


@task(retries=0)
def write_run_log(success: bool, log_text: str, inject: str | None) -> None:
    import psycopg2

    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id SERIAL PRIMARY KEY,
            run_at TIMESTAMP DEFAULT now(),
            success BOOLEAN,
            injected_failure TEXT,
            log TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO pipeline_runs (success, injected_failure, log) VALUES (%s, %s, %s)",
        (success, inject, log_text),
    )
    conn.commit()
    cur.close()
    conn.close()


@flow(name="daily_pipeline")
def daily_pipeline(inject: str | None = None):
    logger = get_logger()
    logger.info("Starting run at %s (inject=%s)", datetime.now(timezone.utc).isoformat(), inject)

    payload = fetch_data(inject)
    load_raw(payload, inject)
    success, log_text = run_dbt()
    write_run_log(success, log_text, inject)

    if not success:
        logger.error("Pipeline FAILED — this is where the Monitor Agent picks up in Stage 1")
        sys.exit(1)

    logger.info("Pipeline succeeded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--break",
        dest="inject",
        choices=["bad_column", "schema_drift", "null_spike"],
        default=None,
        help="Deliberately inject a failure mode for testing the Monitor/Fix agents",
    )
    args = parser.parse_args()
    daily_pipeline(inject=args.inject)
