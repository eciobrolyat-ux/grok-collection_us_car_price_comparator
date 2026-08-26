#!/usr/bin/env python3
"""Scrape Cars.com listings via RapidAPI into DuckDB."""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import duckdb
import requests
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

from vin_decoder import decode_vin_nhtsa

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "listings.duckdb"

load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def get_rapidapi_key(config: dict) -> str:
    key = os.environ.get("RAPIDAPI_KEY") or config.get("rapidapi_key") or ""
    if not key or key.startswith("put-your-key"):
        raise SystemExit(
            "Set RAPIDAPI_KEY in .env (copy .env.example). "
            "Do not commit the real key."
        )
    return key


def connect() -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            scrape_date DATE,
            region VARCHAR,
            seller_zip VARCHAR,
            source VARCHAR,
            vin VARCHAR,
            year INTEGER,
            make VARCHAR,
            model VARCHAR,
            trim VARCHAR,
            nhtsa_trim VARCHAR,
            nhtsa_series VARCHAR,
            nhtsa_body VARCHAR,
            nhtsa_drive VARCHAR,
            price INTEGER,
            mileage INTEGER,
            exterior_color VARCHAR,
            days_on_market INTEGER,
            url VARCHAR,
            first_seen DATE,
            last_seen DATE,
            raw_json VARCHAR
        )
        """
    )
    existing = {
        row[0]
        for row in con.execute("PRAGMA table_info('listings')").fetchall()
    }
    for col, typ in [
        ("seller_zip", "VARCHAR"),
        ("nhtsa_trim", "VARCHAR"),
        ("nhtsa_series", "VARCHAR"),
        ("nhtsa_body", "VARCHAR"),
        ("nhtsa_drive", "VARCHAR"),
        ("first_seen", "DATE"),
        ("last_seen", "DATE"),
    ]:
        if col not in existing:
            con.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")
    return con


def cars_com_search(
    key: str,
    year: int,
    make: str,
    model: str,
    zip_code: str,
    radius: int,
    page: int,
) -> list:
    url = "https://cars-com.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": "cars-com.p.rapidapi.com",
    }
    params = {
        "year_min": year,
        "year_max": year,
        "make": make,
        "model": model,
        "zip": zip_code,
        "radius": radius,
        "page": page,
        "page_size": 100,
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        return payload.get("data") or payload.get("listings") or []
    if isinstance(payload, list):
        return payload
    return []


def upsert_listing(con: duckdb.DuckDBPyConnection, row: dict) -> None:
    today = row["scrape_date"]
    existing = con.execute(
        """
        SELECT first_seen FROM listings
        WHERE source = ? AND vin = ? AND vin <> ''
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        [row["source"], row["vin"]],
    ).fetchone()
    first_seen = existing[0] if existing and existing[0] else today

    con.execute(
        """
        DELETE FROM listings
        WHERE scrape_date = ? AND source = ? AND vin = ? AND region = ?
        """,
        [today, row["source"], row["vin"], row["region"]],
    )
    con.execute(
        """
        INSERT INTO listings (
            scrape_date, region, seller_zip, source, vin, year, make, model,
            trim, nhtsa_trim, nhtsa_series, nhtsa_body, nhtsa_drive,
            price, mileage, exterior_color, days_on_market, url,
            first_seen, last_seen, raw_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?
        )
        """,
        [
            today,
            row["region"],
            row["seller_zip"],
            row["source"],
            row["vin"],
            row["year"],
            row["make"],
            row["model"],
            row["trim"],
            row["nhtsa_trim"],
            row["nhtsa_series"],
            row["nhtsa_body"],
            row["nhtsa_drive"],
            row["price"],
            row["mileage"],
            row["exterior_color"],
            row["days_on_market"],
            row["url"],
            first_seen,
            today,
            row["raw_json"],
        ],
    )


def main() -> None:
    config = load_config()
    key = get_rapidapi_key(config)
    con = connect()
    today = date.today()

    for _region_key, region in config["regions"].items():
        print(f"\n=== Scraping region: {region['name']} ===")
        for target in tqdm(config["targets"]):
            page = 1
            while True:
                listings = cars_com_search(
                    key,
                    target["year"],
                    target["make"],
                    target["model"],
                    region["zip"],
                    region.get("radius", 100),
                    page,
                )
                if not listings:
                    break
                for car in listings:
                    vin = (car.get("vin") or "").strip().upper()
                    decoded = decode_vin_nhtsa(vin) if len(vin) == 17 else {}
                    listing_trim = car.get("trim_level") or car.get("trim") or ""
                    nhtsa_trim = decoded.get("trim") or ""
                    trim = " ".join(p for p in [nhtsa_trim, listing_trim] if p).strip()
                    upsert_listing(
                        con,
                        {
                            "scrape_date": today,
                            "region": region["name"],
                            "seller_zip": car.get("zip")
                            or car.get("dealer_zip")
                            or region["zip"],
                            "source": "cars.com",
                            "vin": vin,
                            "year": target["year"],
                            "make": target["make"],
                            "model": target["model"],
                            "trim": trim,
                            "nhtsa_trim": nhtsa_trim,
                            "nhtsa_series": decoded.get("series") or "",
                            "nhtsa_body": decoded.get("body_class") or "",
                            "nhtsa_drive": decoded.get("drive_type") or "",
                            "price": car.get("price"),
                            "mileage": car.get("mileage"),
                            "exterior_color": car.get("exterior_color"),
                            "days_on_market": car.get("days_on_lot")
                            or car.get("days_on_market"),
                            "url": car.get("listing_url") or car.get("url") or "",
                            "raw_json": str(car),
                        },
                    )
                page += 1
                time.sleep(1.5)
    con.close()
    print(f"Done. Listings are in {DB_PATH}")
    print("Next: streamlit run dashboard.py")


if __name__ == "__main__":
    main()
