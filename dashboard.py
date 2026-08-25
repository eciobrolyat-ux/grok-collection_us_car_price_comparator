# dashboard.py
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DB_PATH = Path("data/listings.duckdb")


@st.cache_resource
def connect():
    if not DB_PATH.exists():
        return None
    return duckdb.connect(str(DB_PATH), read_only=True)


def table_exists(con) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'listings'
        """
    ).fetchone()
    return bool(row and row[0])


def load_filter_options(con):
    return con.execute(
        """
        SELECT
            MIN(year) AS min_year,
            MAX(year) AS max_year,
            LIST(DISTINCT make ORDER BY make) AS makes,
            LIST(DISTINCT model ORDER BY model) AS models,
            LIST(DISTINCT scrape_date ORDER BY scrape_date DESC) AS scrape_dates
        FROM listings
        WHERE year IS NOT NULL
        """
    ).fetchone()


def regional_summary(con, year, make, model, scrape_date, latest_only):
    date_clause = "AND scrape_date = ?" if scrape_date is not None else ""
    latest_cte = """
        latest AS (
            SELECT MAX(scrape_date) AS scrape_date
            FROM filtered
        ),
        scoped AS (
            SELECT f.*
            FROM filtered f
            JOIN latest l ON f.scrape_date = l.scrape_date
        )
    """ if latest_only and scrape_date is None else """
        scoped AS (
            SELECT * FROM filtered
        )
    """

    sql = f"""
        WITH filtered AS (
            SELECT *
            FROM listings
            WHERE year = ?
              AND make ILIKE ?
              AND model ILIKE ?
              AND price IS NOT NULL
              AND price > 0
              {date_clause}
        ),
        {latest_cte}
        SELECT
            region,
            COUNT(*) AS listings,
            MEDIAN(price)::INTEGER AS median_price,
            ROUND(AVG(mileage), 0)::INTEGER AS avg_mileage,
            ROUND(
                MEDIAN(
                    CASE
                        WHEN mileage IS NOT NULL AND mileage > 0
                        THEN price::DOUBLE / mileage
                    END
                ),
                2
            ) AS dollar_per_mile,
            ROUND(
                100.0 * AVG(
                    CASE
                        WHEN UPPER(COALESCE(trim, '')) LIKE '%Z51%' THEN 1.0
                        ELSE 0.0
                    END
                ),
                1
            ) AS pct_z51,
            MIN(scrape_date) AS scrape_from,
            MAX(scrape_date) AS scrape_to
        FROM scoped
        GROUP BY region
        ORDER BY median_price ASC NULLS LAST
    """

    params = [year, f"%{make}%", f"%{model}%"]
    if scrape_date is not None:
        params.append(scrape_date)

    return con.execute(sql, params).df()


def listings_detail(con, year, make, model, scrape_date, latest_only):
    date_clause = "AND scrape_date = ?" if scrape_date is not None else ""
    latest_clause = """
        AND scrape_date = (SELECT MAX(scrape_date) FROM listings
                           WHERE year = ? AND make ILIKE ? AND model ILIKE ?)
    """ if latest_only and scrape_date is None else ""

    sql = f"""
        SELECT
            scrape_date,
            region,
            year,
            make,
            model,
            trim,
            price,
            mileage,
            CASE
                WHEN mileage IS NOT NULL AND mileage > 0
                THEN ROUND(price::DOUBLE / mileage, 2)
            END AS dollar_per_mile,
            days_on_market,
            url
        FROM listings
        WHERE year = ?
          AND make ILIKE ?
          AND model ILIKE ?
          AND price IS NOT NULL
          {date_clause}
          {latest_clause}
        ORDER BY region, price
    """

    params = [year, f"%{make}%", f"%{model}%"]
    if scrape_date is not None:
        params.append(scrape_date)
    if latest_only and scrape_date is None:
        params.extend([year, f"%{make}%", f"%{model}%"])

    return con.execute(sql, params).df()


st.set_page_config(page_title="US Car Price Comparator", layout="wide")
st.title("US Car Price Comparator")

con = connect()
if con is None or not table_exists(con):
    st.error(
        "No listings database found at `data/listings.duckdb`. "
        "Set your RapidAPI key in `config.yaml` and run `python scraper.py` first."
    )
    st.stop()

opts = load_filter_options(con)
if opts is None or opts[0] is None:
    st.warning("The listings table is empty. Run `python scraper.py` first.")
    st.stop()

min_year, max_year, makes, models, scrape_dates = opts
makes = [m for m in (makes or []) if m]
models = [m for m in (models or []) if m]

st.sidebar.header("Filters")
year = st.sidebar.number_input(
    "Year",
    min_value=int(min_year),
    max_value=int(max_year),
    value=min(2015, int(max_year)),
    step=1,
)
make = st.sidebar.selectbox("Make", options=makes, index=makes.index("Chevrolet") if "Chevrolet" in makes else 0)
model = st.sidebar.selectbox("Model", options=models, index=models.index("Corvette") if "Corvette" in models else 0)
latest_only = st.sidebar.checkbox("Latest scrape only", value=True)
scrape_date = None
if not latest_only and scrape_dates:
    scrape_labels = ["All dates"] + [str(d) for d in scrape_dates]
    chosen = st.sidebar.selectbox("Scrape date", scrape_labels)
    if chosen != "All dates":
        scrape_date = chosen
        latest_only = False

summary = regional_summary(con, year, make, model, scrape_date, latest_only)

if summary.empty:
    st.info("No listings match those filters.")
    st.stop()

st.subheader(f"{year} {make} {model} by region")

display = summary.copy()
display["median_price"] = display["median_price"].map(lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
display["avg_mileage"] = display["avg_mileage"].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
display["dollar_per_mile"] = display["dollar_per_mile"].map(lambda x: f"${x:.2f}" if pd.notna(x) else "—")
display["pct_z51"] = display["pct_z51"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
st.dataframe(display, use_container_width=True, hide_index=True)

if len(summary) >= 2 and summary["median_price"].notna().sum() >= 2:
    cheapest = summary.loc[summary["median_price"].idxmin()]
    dearest = summary.loc[summary["median_price"].idxmax()]
    gap = dearest["median_price"] - cheapest["median_price"]
    st.metric(
        "Median price gap",
        f"${gap:,.0f}",
        help=f"{dearest['region']} vs {cheapest['region']}",
    )

st.subheader("Listings")
st.dataframe(
    listings_detail(con, year, make, model, scrape_date, latest_only),
    use_container_width=True,
    hide_index=True,
)
