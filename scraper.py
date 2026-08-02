import os, sys, requests, yaml, duckdb, time
from datetime import datetime
from tqdm import tqdm
from vin_decoder import decode_vin_nhtsa


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def get_api_keys(config, active_sources):
    """Pulls secrets from the keybank vault in-process. The decrypted values
    never get printed/logged here -- they flow straight into request
    headers/params in the search functions below."""
    from keybank import get_secret
    rapid_api_key = get_secret("rapidapi_key") if "cars_com" in active_sources else None
    marketcheck_api_key = get_secret("marketcheck_api_key") if "marketcheck" in active_sources else None
    marketcheck_api_secret = get_secret("marketcheck_api_secret") if "marketcheck" in active_sources else None
    return rapid_api_key, marketcheck_api_key, marketcheck_api_secret


def get_marketcheck_access_token(api_key, api_secret):
    """Exchanges the MarketCheck key/secret pair for a short-lived bearer
    token via OAuth2 client-credentials, once per scraper run."""
    r = requests.post(
        "https://api.marketcheck.com/oauth2/token",
        auth=(api_key, api_secret),
        data={"grant_type": "client_credentials"},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def ensure_schema(con):
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
    # Decoded VIN specs are permanent, unlike the daily price snapshots in
    # `listings` above, so they get their own table and are decoded once.
    con.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        vin VARCHAR,
        trim VARCHAR,
        series VARCHAR,
        body_class VARCHAR,
        engine VARCHAR,
        drive_type VARCHAR,
        decoded_date DATE
    )
    """)


def make_vin_cache(con):
    """Returns a get_decoded(vin) function backed by the `vehicles` table,
    so a given VIN is only ever sent to NHTSA once."""
    cache = {}
    for vin, trim, series, body_class, engine, drive_type in con.execute(
        "SELECT vin, trim, series, body_class, engine, drive_type FROM vehicles"
    ).fetchall():
        cache[vin] = {
            "trim": trim, "series": series, "body_class": body_class,
            "engine": engine, "drive_type": drive_type,
        }

    def get_decoded(vin):
        if not vin:
            return {}
        if vin in cache:
            return cache[vin]
        try:
            decoded = decode_vin_nhtsa(vin)
        except Exception as e:
            print(f"  WARN: VIN decode failed for {vin}: {e}")
            return {}
        cache[vin] = decoded
        con.execute(
            "INSERT INTO vehicles VALUES (?, ?, ?, ?, ?, ?, ?)",
            [vin, decoded.get("trim", ""), decoded.get("series", ""), decoded.get("body_class", ""),
             decoded.get("engine", ""), decoded.get("drive_type", ""), datetime.today().date()],
        )
        return decoded

    return get_decoded


def cars_com_search(year, make, model, zip_code, radius, page, api_key):
    """cars.com listings via RapidAPI. Returns a list of normalized dicts."""
    url = "https://cars-com.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "cars-com.p.rapidapi.com"
    }
    params = {
        "year_min": year, "year_max": year,
        "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "page": page, "page_size": 100
    }
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
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


def marketcheck_search(year, make, model, zip_code, radius, page, access_token):
    """MarketCheck active listings search. Returns a list of normalized dicts.

    NOTE: field names below follow MarketCheck's documented v2 schema
    (docs.marketcheck.com/docs/api/cars). Verify against a live response
    for your account/plan before relying on this in production.
    """
    url = "https://api.marketcheck.com/v2/search/car/active"
    rows = 50
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "year": year, "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "car_type": "used",
        "rows": rows, "start": (page - 1) * rows,
    }
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
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


SOURCE_FNS = {
    "cars_com": cars_com_search,
    "marketcheck": marketcheck_search,
}


def scrape_target(con, get_decoded, search_fn, auth_value, source_name, region, target, today):
    page = 1
    while True:
        listings = search_fn(
            target["year"], target["make"], target["model"],
            region["zip"], region["radius"], page, auth_value
        )
        if not listings:
            break
        for car in listings:
            decoded = get_decoded(car["vin"])
            con.execute("""
            INSERT INTO listings VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """, [
                today, region["name"], source_name, car["vin"],
                target["year"], target["make"], target["model"],
                car["trim"], car["price"], car["mileage"], car["exterior_color"],
                car["days_on_market"], car["url"], str(car["raw"]),
            ])
        page += 1
        time.sleep(1.5)  # be nice


def main():
    config = load_config()
    active_sources = config.get("sources", ["cars_com"])
    rapid_api_key, marketcheck_api_key, marketcheck_api_secret = get_api_keys(config, active_sources)

    auth_values = {}
    if "cars_com" in active_sources:
        auth_values["cars_com"] = rapid_api_key
    if "marketcheck" in active_sources:
        auth_values["marketcheck"] = get_marketcheck_access_token(marketcheck_api_key, marketcheck_api_secret)

    os.makedirs("data", exist_ok=True)
    con = duckdb.connect("data/listings.duckdb")
    ensure_schema(con)
    get_decoded = make_vin_cache(con)

    today = datetime.today().date()
    failures = []

    for region_key, region in config["regions"].items():
        print(f"\n=== Scraping region: {region['name']} ===")
        for source_name in active_sources:
            search_fn = SOURCE_FNS[source_name]
            # Re-running the scraper the same day replaces that day's rows for
            # this region/source instead of accumulating duplicates.
            con.execute(
                "DELETE FROM listings WHERE scrape_date = ? AND region = ? AND source = ?",
                [today, region["name"], source_name],
            )
            for target in tqdm(config["targets"], desc=source_name):
                try:
                    scrape_target(
                        con, get_decoded, search_fn, auth_values[source_name],
                        source_name, region, target, today
                    )
                except Exception as e:
                    msg = f"{region['name']} / {source_name} / {target['year']} {target['make']} {target['model']}: {e}"
                    print(f"  ERROR: {msg}")
                    failures.append(msg)

    con.close()

    if failures:
        print(f"\nDone with {len(failures)} failure(s):")
        for f in failures:
            print(" -", f)
        sys.exit(1)

    print("\nDone! Run `streamlit run dashboard.py` to explore the data.")


if __name__ == "__main__":
    main()
