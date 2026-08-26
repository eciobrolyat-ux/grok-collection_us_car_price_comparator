#!/usr/bin/env python3
"""NHTSA vPIC VIN decode with a local JSON cache."""

from __future__ import annotations

import json
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).resolve().parent / "data" / "vin_cache.json"
VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=0, sort_keys=True))
    tmp.replace(CACHE_PATH)


def decode_vin_nhtsa(vin: str) -> dict:
    vin = (vin or "").strip().upper()
    if len(vin) != 17:
        return {}
    cache = _load_cache()
    if vin in cache:
        return cache[vin]
    try:
        data = requests.get(VPIC_URL.format(vin=vin), timeout=20).json()["Results"][0]
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return {}
    parsed = {
        "trim": data.get("Trim") or "",
        "series": data.get("Series") or "",
        "body_class": data.get("BodyClass") or "",
        "engine": data.get("EngineModel") or "",
        "drive_type": data.get("DriveType") or "",
    }
    cache[vin] = parsed
    _save_cache(cache)
    return parsed
