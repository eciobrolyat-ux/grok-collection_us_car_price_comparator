# dashboard.py
import streamlit as st, duckdb, pandas as pd
con = duckdb.connect("data/listings.duckdb", read_only=True)

st.title("US Car Price Comparator")
make = st.sidebar.text_input("Make", "Chevrolet")
model = st.sidebar.text_input("Model", "Corvette")

available_years = con.execute("""
SELECT DISTINCT year FROM listings
WHERE make ILIKE ? AND model ILIKE ?
ORDER BY year DESC
""", [f"%{make}%", f"%{model}%"]).df()["year"].tolist()

if available_years:
    year = st.sidebar.selectbox("Year", available_years)
else:
    year = st.sidebar.number_input("Year", 1950, 2030, 2017)
    st.sidebar.caption("No scraped data yet for this make/model -- showing a manual year picker.")

available_trims = con.execute("""
SELECT DISTINCT trim FROM listings
WHERE year = ? AND make ILIKE ? AND model ILIKE ? AND trim IS NOT NULL AND trim != ''
ORDER BY trim
""", [year, f"%{make}%", f"%{model}%"]).df()["trim"].tolist()
trim_filter = st.sidebar.selectbox("Trim", ["All"] + available_trims)

available_regions = con.execute("""
SELECT DISTINCT region FROM listings
WHERE year = ? AND make ILIKE ? AND model ILIKE ?
ORDER BY region
""", [year, f"%{make}%", f"%{model}%"]).df()["region"].tolist()
region_filter = st.sidebar.multiselect("Regions", available_regions)

trim_clause = "AND trim = ?" if trim_filter != "All" else ""
trim_params = [trim_filter] if trim_filter != "All" else []
region_clause = f"AND region IN ({', '.join(['?'] * len(region_filter))})" if region_filter else ""
region_params = region_filter

filter_clause = f"{trim_clause} {region_clause}"
base_params = [year, f"%{make}%", f"%{model}%"] + trim_params + region_params

df = con.execute(f"""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ? {filter_clause}
)
SELECT
    region,
    median(price) AS median_price,
    avg(mileage) AS avg_mileage,
    count(*) AS num_listings
FROM latest
WHERE rn = 1
GROUP BY region
ORDER BY median_price
""", base_params).df()

st.subheader("Latest snapshot by region")
st.table(df)

trim_price_df = con.execute(f"""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ? {filter_clause}
)
SELECT trim, region, median(price) AS median_price, count(*) AS num_listings
FROM latest
WHERE rn = 1 AND trim IS NOT NULL AND trim != ''
GROUP BY trim, region
""", base_params).df()

st.subheader("Median price by trim and region")
st.caption("Comparing the same trim across regions avoids mixing base and loaded trims into one number.")
if not trim_price_df.empty:
    price_pivot = trim_price_df.pivot(index="trim", columns="region", values="median_price")
    st.dataframe(price_pivot)
    with st.expander("Listing counts behind each cell"):
        count_pivot = trim_price_df.pivot(index="trim", columns="region", values="num_listings")
        st.dataframe(count_pivot)
else:
    st.caption("No trim data available for this filter.")

condition_df = con.execute(f"""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ? {filter_clause}
)
SELECT
    region,
    count(*) AS num_listings,
    100.0 * count(CASE WHEN carfax_clean_title THEN 1 END) / NULLIF(count(carfax_clean_title), 0) AS pct_clean_title,
    100.0 * count(CASE WHEN carfax_1_owner THEN 1 END) / NULLIF(count(carfax_1_owner), 0) AS pct_one_owner,
    avg(price_change_percent) AS avg_price_change_pct
FROM latest
WHERE rn = 1
GROUP BY region
ORDER BY region
""", base_params).df()

st.subheader("Condition & deal quality by region")
st.caption("Percentages are of listings with known Carfax data -- not every listing includes it.")
st.table(condition_df)

st.subheader("Browse listings")
listings_df = con.execute(f"""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ? {filter_clause}
)
SELECT
    photo_url, region, price, mileage, exterior_color, interior_color,
    trim, days_on_market, last_seen_date, url
FROM latest
WHERE rn = 1
ORDER BY price ASC NULLS LAST
""", base_params).df()

st.dataframe(
    listings_df,
    column_config={
        "photo_url": st.column_config.ImageColumn("Photo"),
        "url": st.column_config.LinkColumn("View listing"),
        "last_seen_date": st.column_config.TextColumn("Last confirmed live"),
    },
    hide_index=True,
)

trend_df = con.execute(f"""
SELECT scrape_date, region, median(price) AS median_price
FROM listings
WHERE year = ? AND make ILIKE ? AND model ILIKE ? {filter_clause}
GROUP BY scrape_date, region
ORDER BY scrape_date
""", base_params).df()

st.subheader("Median price trend over time")
if trend_df["scrape_date"].nunique() > 1:
    pivot = trend_df.pivot(index="scrape_date", columns="region", values="median_price")
    st.line_chart(pivot)
else:
    st.caption("Not enough historical data yet for a trend chart — run the scraper on more than one day.")
