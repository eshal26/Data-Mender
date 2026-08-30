"""
Stage 0 tests — check the fetch/inject logic in isolation (no live DB/API
needed for these; the CI smoke test in ci.yml covers the full run).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestration" / "flows"))

from daily_pipeline import fetch_data  # noqa: E402


def test_null_spike_injection_nulls_humidity():
    payload = fetch_data.fn(inject="null_spike")
    humidity = payload["hourly"]["relative_humidity_2m"]
    assert all(v is None for v in humidity)


def test_no_injection_leaves_data_intact():
    payload = fetch_data.fn(inject=None)
    humidity = payload["hourly"]["relative_humidity_2m"]
    assert any(v is not None for v in humidity)
