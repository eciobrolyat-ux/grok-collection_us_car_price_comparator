# grok-collection_us_car_price_comparator
Price disparity tool for cars in the different regions of the USA

## API keys (keybank)

API keys (e.g. `rapidapi_key`) are never stored in `config.yaml` or any
other file in this repo. Instead they live in an encrypted local vault
managed by `keybank.py`, and scripts pull them in at runtime via
`keybank.get_secret(...)`.

Set it up:

```bash
python keybank.py init                # creates ~/.keybank/vault.json, sets a master password
python keybank.py set rapidapi_key     # prompts for the value with hidden input
python keybank.py list                # shows stored key *names* only
```

Run these commands yourself, in your own terminal, rather than asking an
AI assistant to run them for you — `set` uses a masked `getpass()` prompt
so the raw key never appears as a command argument, in shell history, or
in anything an assistant would see or log. The vault file itself is AES
(Fernet)-encrypted at rest and is git-ignored (`.keybank/`).

When running `scraper.py`, either:
- enter the master password interactively when prompted, or
- export `KEYBANK_PASSWORD` in your shell session beforehand (still never
  put it in a file that gets committed or read by tooling).

Other commands: `python keybank.py get <name>`, `delete <name>`,
`rotate-password`.
