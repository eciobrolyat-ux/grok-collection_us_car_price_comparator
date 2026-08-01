import os, requests, yaml, duckdb, pandas as pd, time
from datetime import datetime
from tqdm import tqdm
from vin_decoder import decode_vin_nhtsa

with open("config.yaml") as f:
    config = yaml.safe_load(f)

active_sources = config.get("sources", ["cars_com"])

rapidapi_key = os.environ.get("RAPIDAPI_KEY", config.get("rapidapi_key"))
if "cars_com" in active_sources and (not rapidapi_key or rapidapi_key == "put-your-key-here-later"):
    raise SystemExit("Set the RAPIDAPI_KEY environment variable before running the scraper.")

marketcheck_api_key = os.environ.get("MARKETCHECK_API_KEY", config.get("marketcheck_api_key"))
if "marketcheck" in active_sources and not marketcheck_api_key:
    raise SystemExit("Set the MARKETCHECK_API_KEY environment variable before running the scraper.")

os.makedirs("data", exist_ok=True)
con = duckdb.connect("data/listings.duckdb")
con.execute("""
CREATE TABLE IF NOT EXISTS listings (
    scrape_date DATE,
    region VARCHAR,
    source VARCHAR,
    vin VARCHAR,
    year INTEGER,
    make VARCHAR,
    model VARCHAR,
    trim VARCHAR,
    price INTEGER,
    mileage INTEGER,
    exterior_color VARCHAR,
    days_on_market INTEGER,
    url VARCHAR,
    raw_json VARCHAR
)
""")


def cars_com_search(year, make, model, zip_code, radius=100, page=1):
    """cars.com listings via RapidAPI. Returns a list of normalized dicts."""
    url = "https://cars-com.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "cars-com.p.rapidapi.com"
    }
    params = {
        "year_min": year, "year_max": year,
        "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "page": page, "page_size": 100
    }
    r = requests.get(url, headers=headers, params=params)
    raw_listings = r.json().get("data", [])
    return [
        {
            "vin": car.get("vin", ""),
            "trim": car.get("trim_level", ""),
            "price": car.get("price"),
            "mileage": car.get("mileage"),
            "exterior_color": car.get("exterior_color"),
            "days_on_market": car.get("days_on_lot"),
            "url": car.get("listing_url", ""),
            "raw": car,
        }
        for car in raw_listings
    ]


def marketcheck_search(year, make, model, zip_code, radius=100, page=1):
    """MarketCheck active listings search. Returns a list of normalized dicts.

    NOTE: field names below follow MarketCheck's documented v2 schema
    (docs.marketcheck.com/docs/api/cars). Verify against a live response
    for your account/plan before relying on this in production.
    """
    url = "https://api.marketcheck.com/v2/search/car/active"
    rows = 50
    params = {
        "api_key": marketcheck_api_key,
        "year": year, "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "car_type": "used",
        "rows": rows, "start": (page - 1) * rows,
    }
    r = requests.get(url, params=params)
    raw_listings = r.json().get("listings", [])
    return [
        {
            "vin": car.get("vin", ""),
            "trim": (car.get("build") or {}).get("trim", ""),
            "price": car.get("price"),
            "mileage": car.get("miles"),
            "exterior_color": car.get("exterior_color"),
            "days_on_market": car.get("dom"),
            "url": car.get("vdp_url", ""),
            "raw": car,
        }
        for car in raw_listings
    ]


SOURCES = {
    "cars_com": cars_com_search,
    "marketcheck": marketcheck_search,
}

today = datetime.today().date()

for region_key, region in config["regions"].items():
    print(f"\n=== Scraping region: {region['name']} ===")
    for source_name in active_sources:
        search_fn = SOURCES[source_name]
        # Re-running the scraper the same day replaces that day's rows for
        # this region/source instead of accumulating duplicates.
        con.execute(
            "DELETE FROM listings WHERE scrape_date = ? AND region = ? AND source = ?",
            [today, region["name"], source_name],
        )
        for target in tqdm(config["targets"], desc=source_name):
            page = 1
            while True:
                listings = search_fn(
                    target["year"], target["make"], target["model"],
                    region["zip"], region["radius"], page
                )
                if not listings:
                    break
                for car in listings:
                    vin = car["vin"]
                    decoded = decode_vin_nhtsa(vin) if vin else {}
                    con.execute("""
                    INSERT INTO listings VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """, [
                        today,
                        region["name"],
                        source_name,
                        vin,
                        target["year"],
                        target["make"],
                        target["model"],
                        (decoded.get("trim", "") + " " + car["trim"]).strip(),
                        car["price"],
                        car["mileage"],
                        car["exterior_color"],
                        car["days_on_market"],
                        car["url"],
                        str(car["raw"]),
                    ])
                page += 1
                time.sleep(1.5)  # be nice
con.close()
print("Done! Run `streamlit run dashboard.py` to explore the data.")
