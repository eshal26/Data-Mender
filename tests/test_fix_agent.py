"""
Stage 2 tests — placeholder. Once fix.py's propose_fix() is implemented,
test that a canned BAD_DATA classification produces a fix that (a) parses
back into valid SQL and (b) doesn't silently drop the whole table (guard
against the "tests pass but data is gone" failure mode called out in the
README talking points).
"""
import pytest


@pytest.mark.skip(reason="Implement once Stage 2 Fix Agent prompt is finalized")
def test_proposed_fix_is_valid_sql():
    pass


@pytest.mark.skip(reason="Implement once Stage 2 Fix Agent prompt is finalized")
def test_proposed_fix_does_not_silently_drop_all_rows():
    pass
