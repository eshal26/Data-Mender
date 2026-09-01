"""
Stage 0 tests — check the fetch/inject logic in isolation (no live DB/API
needed for these; the CI smoke test in ci.yml covers the full run).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestration" / "flows"))

from daily_pipeline import fetch_data  # noqa: E402


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "hourly": {
                "time": ["2026-08-31T00:00", "2026-08-31T01:00"],
                "temperature_2m": [30.5, 31.0],
                "relative_humidity_2m": [70, 72],
                "precipitation": [0.0, 0.1],
            }
        }


def test_null_spike_injection_nulls_humidity(monkeypatch):
    monkeypatch.setattr(
        "daily_pipeline.requests.get", lambda *args, **kwargs: FakeResponse()
    )

    payload = fetch_data.fn(inject="null_spike")
    humidity = payload["hourly"]["relative_humidity_2m"]
    assert all(v is None for v in humidity)


def test_no_injection_leaves_data_intact(monkeypatch):
    monkeypatch.setattr(
        "daily_pipeline.requests.get", lambda *args, **kwargs: FakeResponse()
    )

    payload = fetch_data.fn(inject=None)
    humidity = payload["hourly"]["relative_humidity_2m"]
    assert any(v is not None for v in humidity)
