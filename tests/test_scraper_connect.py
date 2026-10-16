"""Step 1 check: scraper.connect() must work on a fresh and on an existing database.

No network: the listings search and the NHTSA decode are never called here.
The database and VIN cache are redirected to a temporary folder.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def scraper(tmp_path, monkeypatch):
    import vin_decoder

    monkeypatch.setattr(vin_decoder, "CACHE_PATH", tmp_path / "vin_cache.json")
    mod = importlib.import_module("scraper")
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "listings.duckdb")
    monkeypatch.setattr(mod.requests, "get", _no_network)
    return mod


def _no_network(*args, **kwargs):
    raise AssertionError("network call attempted during test")


def _columns(con) -> set[str]:
    return {row[1] for row in con.execute("PRAGMA table_info('listings')").fetchall()}


def test_connect_on_fresh_database(scraper):
    con = scraper.connect()
    cols = _columns(con)
    con.close()
    assert "seller_zip" in cols
    assert "last_seen" in cols
    assert "raw_json" in cols


def test_connect_twice_is_idempotent(scraper):
    scraper.connect().close()
    con = scraper.connect()
    cols = _columns(con)
    con.close()
    assert "seller_zip" in cols


def test_connect_migrates_old_table(scraper):
    import duckdb

    con = duckdb.connect(str(scraper.DB_PATH))
    con.execute("CREATE TABLE listings (scrape_date DATE, region VARCHAR, vin VARCHAR)")
    con.close()

    con = scraper.connect()
    cols = _columns(con)
    con.close()
    assert {"seller_zip", "nhtsa_trim", "first_seen", "last_seen"} <= cols
