"""
field_audit.py -- inspect the raw API responses already sitting in
data/listings.duckdb to see every field a source actually returns, and how
often each one is populated. Run this against real scraped data to decide
what's worth promoting into real columns (currently only a handful of
fields get parsed out in scraper.py; everything else is discarded).

Usage:
    python field_audit.py [source]   # source defaults to "marketcheck"
"""
import ast
import json
import sys
from collections import Counter

import duckdb


def parse_raw(raw_json):
    """raw_json is proper JSON for rows scraped after the json.dumps fix,
    but older rows were stored via Python's str() -- fall back to that."""
    try:
        return json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return ast.literal_eval(raw_json)


def walk(obj, prefix, field_counts, example_values):
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            field_counts[path] += 1
            if path not in example_values and not isinstance(value, (dict, list)):
                example_values[path] = value
            walk(value, path, field_counts, example_values)
    elif isinstance(obj, list) and obj:
        # Lists (e.g. media/photos) vary in length -- just show the shape
        # of the first element rather than counting each index separately.
        walk(obj[0], prefix + "[]", field_counts, example_values)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "marketcheck"
    con = duckdb.connect("data/listings.duckdb", read_only=True)
    rows = con.execute(
        "SELECT raw_json FROM listings WHERE source = ?", [source]
    ).fetchall()

    if not rows:
        print(f"No rows found for source='{source}'. Run scraper.py first.")
        return

    field_counts = Counter()
    example_values = {}
    parsed = 0
    for (raw_json,) in rows:
        if not raw_json:
            continue
        try:
            data = parse_raw(raw_json)
        except Exception as e:
            print(f"  WARN: couldn't parse a raw_json row: {e}")
            continue
        parsed += 1
        walk(data, "", field_counts, example_values)

    print(f"Analyzed {parsed}/{len(rows)} '{source}' listings\n")
    print(f"{'field path':45} {'present':>12}   example value")
    print("-" * 90)
    for path, count in sorted(field_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        pct = 100 * count / parsed
        example = example_values.get(path, "")
        print(f"{path:45} {count}/{parsed} ({pct:3.0f}%)   {example!r}")


if __name__ == "__main__":
    main()
