"""Run 5: the cleaner erases asset names between cycles (user, 2026-11-04). Fixture data only, no API call."""
import re
from pathlib import Path

from apex import config
from apex.env_connector import Connector

ROOT = Path(__file__).resolve().parent.parent
F7 = ROOT / "tests" / "fixtures" / "chunks_small_7.json"


def rules():
    conn = Connector(config.load(), F7)
    return conn, conn.cleaning_rules()


# 1
def test_asset_names_match():
    _, r = rules()
    pats = [re.compile(p) for p in r["patterns"]]
    hit = lambda s: any(p.search(s) for p in pats)
    for s in ("Asset C jumped late in the month", "w['Asset AB'] = 0.2", "Asset Z"):
        assert hit(s), s
    for s in ("asset class rotation", "Asset Class", "history.assets", "an Asset"):
        assert not hit(s), s
    assert "asset names" in r["what_counts_as_data"]


# 2
def test_brief_warns():
    conn, _ = rules()
    conn.release(0)
    assert "history.assets" in conn.brief() and "names are erased" in conn.brief()
