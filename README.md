# grok-collection_us_car_price_comparator
Price disparity tool for cars in the different regions of the USA

## API keys (keybank)

API keys (e.g. `rapidapi_key`) are never stored in `config.yaml` or any
other file in this repo. Instead they live in an encrypted local vault
managed by [keybank](https://github.com/eciobrolyat-ux/keybank), a
separate, standalone tool (not specific to this project — use it for any
project's secrets, e.g. financial broker API keys). Scripts here pull
keys in at runtime via `keybank.get_secret(...)`.

`pip install -r requirements.txt` installs `keybank` from its repo, which
gives you both a `keybank` command and the `keybank` Python module. Set
it up:

```bash
keybank init                # creates ~/.keybank/vault.json, sets a master password
keybank set rapidapi_key    # prompts for the value with hidden input
keybank list                # shows stored key *names* only
```

Run these commands yourself, in your own terminal, rather than asking an
AI assistant to run them for you — `set` uses a masked `getpass()` prompt
so the raw key never appears as a command argument, in shell history, or
in anything an assistant would see or log. The vault file itself is AES
(Fernet)-encrypted at rest and lives outside this repo (`~/.keybank` by
default), so it's never something this project's `.gitignore` even needs
to worry about.

When running `scraper.py`, either:
- enter the master password interactively when prompted, or
- export `KEYBANK_PASSWORD` in your shell session beforehand (still never
  put it in a file that gets committed or read by tooling).

Other commands: `keybank get <name>`, `delete <name>`, `rotate-password`.
See the [keybank README](https://github.com/eciobrolyat-ux/keybank) for
full details.
