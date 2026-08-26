#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p data
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your RapidAPI key there."
else
  echo ".env already exists; left it alone."
fi

echo
echo "Ready. Next:"
echo "  source .venv/bin/activate"
echo "  # put RAPIDAPI_KEY in .env"
echo "  python scraper.py"
echo "  streamlit run dashboard.py"
