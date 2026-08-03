"""
arbitrage_report.py -- looks for regional price gaps on near-new cars.

For each (year, make, model, trim) with more than one region represented
among listings under 5,000 miles, reports cases where the cheapest and
priciest examples differ by $10,000 or more and sit in different regions
(so it's a real regional gap, not just two listings in the same market).

Usage:
    python arbitrage_report.py [min_gap] [max_mileage]
    # both optional, default to 10000 and 5000
"""
import sys

import duckdb

MIN_GAP = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
MAX_MILEAGE = int(sys.argv[2]) if len(sys.argv) > 2 else 5_000


def main():
    con = duckdb.connect("data/listings.duckdb", read_only=True)
    df = con.execute("""
    WITH latest AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
        FROM listings
        WHERE mileage < ?
    )
    SELECT
        year, make, model, trim,
        min(price) AS min_price,
        max(price) AS max_price,
        max(price) - min(price) AS price_gap,
        arg_min(region, price) AS cheap_region,
        arg_max(region, price) AS expensive_region,
        arg_min(mileage, price) AS cheap_mileage,
        arg_max(mileage, price) AS expensive_mileage,
        arg_min(url, price) AS cheap_url,
        arg_max(url, price) AS expensive_url,
        count(*) AS num_listings
    FROM latest
    WHERE rn = 1 AND trim IS NOT NULL AND trim != '' AND price IS NOT NULL
    GROUP BY year, make, model, trim
    HAVING max(price) - min(price) >= ?
       AND arg_min(region, price) != arg_max(region, price)
    ORDER BY price_gap DESC
    """, [MAX_MILEAGE, MIN_GAP]).df()

    if df.empty:
        print(f"No {MIN_GAP}+ regional price gaps found among listings under {MAX_MILEAGE} miles.")
        return

    print(f"{len(df)} regional price gap(s) of ${MIN_GAP:,}+ among listings under {MAX_MILEAGE:,} miles:\n")
    for _, row in df.iterrows():
        print(f"{row.year} {row.make} {row.model} {row.trim}  --  gap: ${row.price_gap:,.0f}")
        print(f"  Cheap:      ${row.min_price:,.0f} in {row.cheap_region} ({row.cheap_mileage:,.0f} mi)")
        print(f"              {row.cheap_url}")
        print(f"  Expensive:  ${row.max_price:,.0f} in {row.expensive_region} ({row.expensive_mileage:,.0f} mi)")
        print(f"              {row.expensive_url}")
        print(f"  ({row.num_listings} listings under {MAX_MILEAGE:,} mi in this year/make/model/trim)\n")


if __name__ == "__main__":
    main()
