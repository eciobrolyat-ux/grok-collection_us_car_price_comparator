import requests, yaml, duckdb, pandas as pd, time
from datetime import datetime
from tqdm import tqdm

from keybank import get_secret

with open("config.yaml") as f:
    config = yaml.safe_load(f)

RAPIDAPI_KEY = get_secret("rapidapi_key", config.get("rapidapi_key"))

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
    url = "https://cars-com.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "cars-com.p.rapidapi.com"
    }
    params = {
        "year_min": year, "year_max": year,
        "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "page": page, "page_size": 100
    }
    r = requests.get(url, headers=headers, params=params)
    return r.json().get("data", [])

for region_key, region in config["regions"].items():
    print(f"\n=== Scraping region: {region['name']} ===")
    for target in tqdm(config["targets"]):
        page = 1
        while True:
            listings = cars_com_search(
                target["year"], target["make"], target["model"],
                region["zip"], region["radius"], page
            )
            if not listings:
                break
            for car in listings:
                vin = car.get("vin", "")
                decoded = decode_vin_nhtsa(vin) if vin else {}
                con.execute("""
                INSERT INTO listings VALUES (
                    ?, ?, 'cars.com', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """, [
                    datetime.today().date(),
                    region["name"],
                    vin,
                    target["year"],
                    target["make"],
                    target["model"],
                    decoded.get("trim", "") + " " + car.get("trim_level", ""),
                    car.get("price"),
                    car.get("mileage"),
                    car.get("exterior_color"),
                    car.get("days_on_lot"),
                    car.get("listing_url", ""),
                    str(car)
                ])
            page += 1
            time.sleep(1.5)  # be nice
con.close()
print("Done! Run the analyzer notebook now.")
