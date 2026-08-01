# grok-collection_us_car_price_comparator
Price disparity tool for cars in the different regions of the USA

## Setup

```
pip install -r requirements.txt
```

Set API keys as environment variables (do not put real keys in `config.yaml`):

```
export RAPIDAPI_KEY=...        # required if "cars_com" is in config.yaml's `sources`
export MARKETCHECK_API_KEY=... # required if "marketcheck" is in config.yaml's `sources`
```

Edit `config.yaml` to choose which sources, regions, and target vehicles (year/make/model)
to track.

## Usage

```
python scraper.py          # scrape configured regions/targets into data/listings.duckdb
streamlit run dashboard.py # browse price comparisons and trends
```

Run the scraper daily (e.g. via cron) to build up history — the dashboard's trend chart
needs more than one day of data to plot anything.

Re-running the scraper on the same day replaces that day's rows for each region/source
rather than duplicating them, so it's safe to re-run after a failed or partial scrape.

## Data sources

- **cars.com** (via RapidAPI)
- **MarketCheck** — field names in `scraper.py` follow MarketCheck's documented v2 API
  schema; verify against a live response for your account/plan before relying on it in
  production.

Both sources tag rows with a `source` column, so results can be compared or filtered by
provider in the dashboard queries.
