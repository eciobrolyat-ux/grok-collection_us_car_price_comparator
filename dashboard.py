# dashboard.py
import streamlit as st, duckdb, pandas as pd
con = duckdb.connect("data/listings.duckdb", read_only=True)

st.title("US Car Price Comparator")
year = st.sidebar.number_input("Year", 2000, 2025, 2015)
make = st.sidebar.text_input("Make", "Chevrolet")
model = st.sidebar.text_input("Model", "Corvette")

df = con.execute(f"""
SELECT region, median_price, avg_mileage, dollar_per_mile, pct_z51
FROM ( ... same query as above ...)
WHERE year={year} AND make ILIKE '%{make}%' AND model ILIKE '%{model}%'
""").df()

st.table(df)
