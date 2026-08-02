# dashboard.py
import streamlit as st, duckdb, pandas as pd
con = duckdb.connect("data/listings.duckdb", read_only=True)

st.title("US Car Price Comparator")
year = st.sidebar.number_input("Year", 2000, 2025, 2015)
make = st.sidebar.text_input("Make", "Chevrolet")
model = st.sidebar.text_input("Model", "Corvette")

df = con.execute("""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ?
)
SELECT
    latest.region,
    median(latest.price) AS median_price,
    avg(latest.mileage) AS avg_mileage,
    avg(latest.price::DOUBLE / NULLIF(latest.mileage, 0)) AS dollar_per_mile,
    sum(CASE
        WHEN latest.trim ILIKE '%Z51%' OR v.trim ILIKE '%Z51%' OR v.series ILIKE '%Z51%'
        THEN 1 ELSE 0
    END) AS count_z51,
    100.0 * sum(CASE
        WHEN latest.trim ILIKE '%Z51%' OR v.trim ILIKE '%Z51%' OR v.series ILIKE '%Z51%'
        THEN 1 ELSE 0
    END) / count(*) AS pct_z51
FROM latest
LEFT JOIN vehicles v ON v.vin = latest.vin
WHERE latest.rn = 1
GROUP BY latest.region
ORDER BY median_price
""", [year, f"%{make}%", f"%{model}%"]).df()

st.subheader("Latest snapshot by region")
st.table(df)

condition_df = con.execute("""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ?
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
""", [year, f"%{make}%", f"%{model}%"]).df()

st.subheader("Condition & deal quality by region")
st.caption("Percentages are of listings with known Carfax data -- not every listing includes it.")
st.table(condition_df)

st.subheader("Browse listings")
listings_df = con.execute("""
WITH latest AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY vin ORDER BY scrape_date DESC) AS rn
    FROM listings
    WHERE year = ? AND make ILIKE ? AND model ILIKE ?
)
SELECT
    photo_url, heading, region, price, mileage, exterior_color, interior_color,
    trim, carfax_clean_title, carfax_1_owner, days_on_market,
    dealer_name, dealer_city, dealer_state, dealer_phone, dealer_website, url
FROM latest
WHERE rn = 1
ORDER BY price ASC NULLS LAST
""", [year, f"%{make}%", f"%{model}%"]).df()

st.dataframe(
    listings_df,
    column_config={
        "photo_url": st.column_config.ImageColumn("Photo"),
        "url": st.column_config.LinkColumn("Listing"),
        "dealer_website": st.column_config.LinkColumn("Dealer site"),
    },
    hide_index=True,
)

trend_df = con.execute("""
SELECT scrape_date, region, median(price) AS median_price
FROM listings
WHERE year = ? AND make ILIKE ? AND model ILIKE ?
GROUP BY scrape_date, region
ORDER BY scrape_date
""", [year, f"%{make}%", f"%{model}%"]).df()

st.subheader("Median price trend over time")
if trend_df["scrape_date"].nunique() > 1:
    pivot = trend_df.pivot(index="scrape_date", columns="region", values="median_price")
    st.line_chart(pivot)
else:
    st.caption("Not enough historical data yet for a trend chart — run the scraper on more than one day.")
