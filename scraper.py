import os, sys, json, requests, yaml, duckdb, time
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


def _raise_with_body(r):
    """raise_for_status(), but with the response body attached -- providers
    put the actual reason (bad scope, wrong plan, malformed auth, ...) in
    the JSON/text body, which raise_for_status() alone discards."""
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        raise requests.HTTPError(f"{e} | response body: {r.text[:500]}") from None


def get_marketcheck_access_token(api_key, api_secret):
    """Exchanges the MarketCheck key/secret pair for a short-lived bearer
    token via OAuth2 client-credentials, once per scraper run."""
    r = requests.post(
        "https://api.marketcheck.com/oauth2/token",
        auth=(api_key, api_secret),
        data={"grant_type": "client_credentials"},
    )
    _raise_with_body(r)
    return r.json()["access_token"]


LISTINGS_NEW_COLUMNS = [
    ("heading", "VARCHAR"),
    ("interior_color", "VARCHAR"),
    ("body_type", "VARCHAR"),
    ("photo_url", "VARCHAR"),
    ("carfax_1_owner", "BOOLEAN"),
    ("carfax_clean_title", "BOOLEAN"),
    ("ref_price", "INTEGER"),
    ("price_change_percent", "DOUBLE"),
    ("first_seen_date", "VARCHAR"),
    ("last_seen_date", "VARCHAR"),
    ("dealer_name", "VARCHAR"),
    ("dealer_city", "VARCHAR"),
    ("dealer_state", "VARCHAR"),
    ("dealer_phone", "VARCHAR"),
    ("dealer_website", "VARCHAR"),
    ("dealer_type", "VARCHAR"),
]


def ensure_schema(con):
    con.execute(f"""
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
        raw_json VARCHAR,
        {", ".join(f"{name} {sql_type}" for name, sql_type in LISTINGS_NEW_COLUMNS)}
    )
    """)
    # ALTER for tables that already existed before these columns were added --
    # CREATE TABLE IF NOT EXISTS above is a no-op on an existing table, so
    # this is what actually brings older databases up to date without
    # losing previously scraped data.
    for name, sql_type in LISTINGS_NEW_COLUMNS:
        con.execute(f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {name} {sql_type}")
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
    """cars.com listings via RapidAPI. Returns (normalized dicts, page_size)."""
    url = "https://cars-com.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "cars-com.p.rapidapi.com"
    }
    page_size = 100
    params = {
        "year_min": year, "year_max": year,
        "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "page": page, "page_size": page_size
    }
    r = requests.get(url, headers=headers, params=params)
    _raise_with_body(r)
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
            # cars.com's RapidAPI response doesn't carry these fields
            "heading": "", "interior_color": "", "body_type": "", "photo_url": "",
            "carfax_1_owner": None, "carfax_clean_title": None,
            "ref_price": None, "price_change_percent": None,
            "first_seen_date": "", "last_seen_date": "",
            "dealer_name": "", "dealer_city": "", "dealer_state": "",
            "dealer_phone": "", "dealer_website": "", "dealer_type": "",
        }
        for car in raw_listings
    ], page_size


def marketcheck_search(year, make, model, zip_code, radius, page, api_key):
    """MarketCheck active listings search. Returns (normalized dicts, page_size).

    Uses the basic api_key-as-query-param auth rather than OAuth2
    client-credentials -- the latter returned "invalid authentication
    credentials" on the search endpoint, likely a plan-tier restriction.

    NOTE: field names below follow MarketCheck's documented v2 schema
    (docs.marketcheck.com/docs/api/cars). Verify against a live response
    for your account/plan before relying on this in production.
    """
    url = "https://api.marketcheck.com/v2/search/car/active"
    rows = 50
    params = {
        "api_key": api_key,
        "year": year, "make": make, "model": model,
        "zip": zip_code, "radius": radius,
        "car_type": "used",
        "rows": rows, "start": (page - 1) * rows,
    }
    r = requests.get(url, params=params)
    _raise_with_body(r)
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
            "heading": car.get("heading", ""),
            "interior_color": car.get("interior_color", ""),
            "body_type": (car.get("build") or {}).get("body_type", ""),
            "photo_url": ((car.get("media") or {}).get("photo_links") or [""])[0],
            "carfax_1_owner": car.get("carfax_1_owner"),
            "carfax_clean_title": car.get("carfax_clean_title"),
            "ref_price": car.get("ref_price"),
            "price_change_percent": car.get("price_change_percent"),
            "first_seen_date": car.get("first_seen_at_date", ""),
            "last_seen_date": car.get("last_seen_at_date", ""),
            "dealer_name": (car.get("dealer") or {}).get("name", ""),
            "dealer_city": (car.get("dealer") or {}).get("city", ""),
            "dealer_state": (car.get("dealer") or {}).get("state", ""),
            "dealer_phone": (car.get("dealer") or {}).get("phone", ""),
            "dealer_website": (car.get("dealer") or {}).get("website", ""),
            "dealer_type": (car.get("dealer") or {}).get("dealer_type", ""),
        }
        for car in raw_listings
    ], rows


SOURCE_FNS = {
    "cars_com": cars_com_search,
    "marketcheck": marketcheck_search,
}


def expand_target_years(target):
    """A target with year_min/year_max expands into one single-year target
    per year in that range (each year is a separate API call, since we
    can't rely on every provider supporting range filtering the same way).
    A target with a plain `year` passes through unchanged."""
    if "year_min" in target and "year_max" in target:
        return [
            {"year": y, "make": target["make"], "model": target["model"]}
            for y in range(target["year_min"], target["year_max"] + 1)
        ]
    return [target]


LISTINGS_BASE_COLUMNS = [
    "scrape_date", "region", "source", "vin", "year", "make", "model",
    "trim", "price", "mileage", "exterior_color", "days_on_market", "url", "raw_json",
]


def scrape_target(con, get_decoded, search_fn, auth_value, source_name, region, target, today):
    page = 1
    columns = LISTINGS_BASE_COLUMNS + [name for name, _ in LISTINGS_NEW_COLUMNS]
    placeholders = ", ".join(["?"] * len(columns))
    insert_sql = f"INSERT INTO listings ({', '.join(columns)}) VALUES ({placeholders})"

    while True:
        listings, page_size = search_fn(
            target["year"], target["make"], target["model"],
            region["zip"], region["radius"], page, auth_value
        )
        if not listings:
            break
        for car in listings:
            decoded = get_decoded(car["vin"])
            base_values = [
                today, region["name"], source_name, car["vin"],
                target["year"], target["make"], target["model"],
                car["trim"], car["price"], car["mileage"], car["exterior_color"],
                car["days_on_market"], car["url"], json.dumps(car["raw"]),
            ]
            extra_values = [car[name] for name, _ in LISTINGS_NEW_COLUMNS]
            con.execute(insert_sql, base_values + extra_values)
        if len(listings) < page_size:
            break
        page += 1
        time.sleep(1.5)  # be nice


MAX_CACHE_AGE_DAYS = 30


def get_last_scrape_date(con):
    result = con.execute("SELECT MAX(scrape_date) FROM listings").fetchone()
    return result[0] if result else None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true",
        help=f"Scrape even if cached data is less than {MAX_CACHE_AGE_DAYS} days old.",
    )
    args = parser.parse_args()

    os.makedirs("data", exist_ok=True)
    con = duckdb.connect("data/listings.duckdb")
    ensure_schema(con)

    today = datetime.today().date()
    last_scrape_date = get_last_scrape_date(con)
    if not args.force and last_scrape_date is not None:
        age_days = (today - last_scrape_date).days
        if age_days < MAX_CACHE_AGE_DAYS:
            print(
                f"Cached data is {age_days} day(s) old (last scraped {last_scrape_date}) "
                f"-- still under the {MAX_CACHE_AGE_DAYS}-day limit, skipping scrape."
            )
            print("Run with --force to scrape anyway.")
            con.close()
            return

    config = load_config()
    active_sources = config.get("sources", ["cars_com"])
    rapid_api_key, marketcheck_api_key, marketcheck_api_secret = get_api_keys(config, active_sources)

    auth_values = {}
    if "cars_com" in active_sources:
        auth_values["cars_com"] = rapid_api_key
    if "marketcheck" in active_sources:
        auth_values["marketcheck"] = marketcheck_api_key

    get_decoded = make_vin_cache(con)

    failures = []

    year_targets = [yt for target in config["targets"] for yt in expand_target_years(target)]

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
            for target in tqdm(year_targets, desc=source_name):
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
