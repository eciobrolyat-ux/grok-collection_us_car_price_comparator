# US Car Price Comparator

Regional used-car asking-price monitor aimed at a geographic-arbitrage screen into Tennessee.

This is not yet a full landed-cost edge. After a scrape you get comps by region. Net profit after transport and tax is the next layer.

## Setup

```bash
chmod +x setup.sh
./setup.sh
source .venv/bin/activate
```

Put your RapidAPI Cars.com key in `.env` as `RAPIDAPI_KEY`. Never commit `.env`.

## Run

```bash
python scraper.py
streamlit run dashboard.py
```

`scraper.py` writes `data/listings.duckdb`. VIN decodes are cached in `data/vin_cache.json`. Both are gitignored.

## Config

`config.yaml` has destination Nashville, source metros (Houston, Dallas, DC), and a small target list: 2015 Corvette plus Camry and F-150 for liquidity.

## Still needed before this is an edge

- Transport quote + TN use-tax in a deals view
- Title / flood filter
- Daily scrape + alert on still-listed VINs above a net threshold
