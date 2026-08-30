"""
Stage 1 tests — placeholder. Once monitor.py's classify() is implemented,
test it against a few canned log fixtures (one per failure category) and
assert the CATEGORY line matches, without requiring a live Ollama call in
CI (mock the requests.post call).
"""
import pytest


@pytest.mark.skip(reason="Implement once Stage 1 Monitor Agent prompt is finalized")
def test_classifies_bad_column_failure():
    pass


@pytest.mark.skip(reason="Implement once Stage 1 Monitor Agent prompt is finalized")
def test_classifies_schema_drift_failure():
    pass
