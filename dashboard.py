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
