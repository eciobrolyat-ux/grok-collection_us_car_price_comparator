# grok-collection_us_car_price_comparator
Price disparity tool for cars in the different regions of the USA

## Setup

```
pip install -r requirements.txt
```

API keys are pulled from a [keybank](https://pypi.org/project/keybank/) vault at runtime — never store
real keys in `config.yaml`. Store these secrets once, ahead of time:

```
keybank set rapidapi_key           # required if "cars_com" is in config.yaml's `sources`
keybank set marketcheck_api_key    # required if "marketcheck" is in config.yaml's `sources`
keybank set marketcheck_api-secret # required if "marketcheck" is in config.yaml's `sources`
```

(run `keybank list` any time to confirm the exact secret names in your vault)

Then, before running the scraper, unlock the vault yourself in your own terminal:

```
export KEYBANK_PASSWORD=...
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
- **MarketCheck** — authenticates via OAuth2 client-credentials (key/secret exchanged for a
  short-lived bearer token once per scraper run). Field names in `scraper.py` follow
  MarketCheck's documented v2 API schema; verify against a live response for your
  account/plan before relying on it in production.

Both sources tag rows with a `source` column, so results can be compared or filtered by
provider in the dashboard queries.
