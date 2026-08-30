"""
Stage 5 — Streamlit dashboard.

Shows pipeline run history from `pipeline_runs` (success/fail over time,
which injected failures were tested, and — once Stages 1-4 exist — how many
were auto-diagnosed, auto-fixed, and PR'd vs escalated to a human).
"""
import os

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

PG_DSN = (
    f"host={os.getenv('POSTGRES_HOST', 'postgres')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')} "
    f"dbname={os.getenv('POSTGRES_DB', 'shp')} "
    f"user={os.getenv('POSTGRES_USER', 'shp')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'shp')}"
)

st.set_page_config(page_title="Self-Healing Pipeline", layout="wide")
st.title("Self-Healing Data Pipeline — Health Dashboard")


@st.cache_data(ttl=30)
def load_runs() -> pd.DataFrame:
    conn = psycopg2.connect(PG_DSN)
    df = pd.read_sql(
        "SELECT id, run_at, success, injected_failure FROM pipeline_runs ORDER BY run_at DESC",
        conn,
    )
    conn.close()
    return df


try:
    df = load_runs()
except Exception as e:
    st.warning(f"Couldn't reach Postgres yet — run the pipeline at least once first. ({e})")
    st.stop()

if df.empty:
    st.info("No pipeline runs yet. Run `python orchestration/flows/daily_pipeline.py`.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Total runs", len(df))
col2.metric("Successful", int(df["success"].sum()))
col3.metric("Failed", int((~df["success"]).sum()))

st.subheader("Run history")
st.dataframe(df, use_container_width=True)

st.subheader("Success rate over time")
df_sorted = df.sort_values("run_at")
st.line_chart(df_sorted.set_index("run_at")["success"].astype(int))
