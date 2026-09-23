#!/usr/bin/env python3
"""
Gold & Silver Price Tracker - Nepal (NPR per tola).

Pulls the daily FENEGOSIDA-sourced rate from ashesh.com.np's public gold
widget page (plain server-rendered HTML, updated once daily after ~11am
NPT) and stores it in its own local SQLite database. Deliberately kept
fully independent of the news pipeline in main.py - separate script,
separate database, separate schedule.

Usage:
    python prices.py fetch     # fetch today's rates and store them
    python prices.py latest    # print the most recently stored rates
"""
import argparse
import logging
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "data" / "prices.db"
SOURCE_URL = "https://www.ashesh.com.np/gold/widget.php"
REQUEST_TIMEOUT = 15

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("gold_silver_prices")

SCHEMA = """
CREATE TABLE IF NOT EXISTS metal_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    source_date TEXT,
    metal TEXT NOT NULL,
    unit TEXT NOT NULL,
    price_npr INTEGER NOT NULL
);
"""

# The page repeats each metal twice (once per-tola block, once per-10-gram
# block); splitting on the block-start marker and scanning each chunk for
# its own name/rate/unit is simpler and more robust than trying to match
# balanced closing </div> tags.
BLOCK_START = '<div class="country">'
NAME_RE = re.compile(r'<div class="name">\s*([^<]+?)\s*</div>')
RATE_RE = re.compile(r'<div class="rate_buying">\s*(\d+)\s*</div>')
UNIT_RE = re.compile(r'<div class="unit">\s*([^<]+?)\s*</div>')
DATE_RE = re.compile(r'<div class="header_date">\s*([^<]+?)\s*</div>')


@contextmanager
def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def fetch_page() -> str:
    resp = requests.get(SOURCE_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def parse_prices(html: str) -> list:
    """Extract the per-tola Gold Hallmark / Gold Tajabi / Silver rates."""
    date_match = DATE_RE.search(html)
    source_date = date_match.group(1).strip() if date_match else None

    results = []
    for block in html.split(BLOCK_START)[1:]:
        name_m = NAME_RE.search(block)
        rate_m = RATE_RE.search(block)
        unit_m = UNIT_RE.search(block)
        if not (name_m and rate_m and unit_m):
            continue
        unit = unit_m.group(1).strip()
        if unit.lower() != "tola":
            continue
        results.append({
            "metal": name_m.group(1).strip(),
            "unit": unit,
            "price_npr": int(rate_m.group(1)),
            "source_date": source_date,
        })
    return results


def cmd_fetch(_args) -> int:
    init_db()
    html = fetch_page()
    prices = parse_prices(html)
    if not prices:
        logger.error("Could not find any per-tola prices in the page - the site's HTML may have changed")
        return 1

    fetched_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO metal_prices (fetched_at, source_date, metal, unit, price_npr) VALUES (?, ?, ?, ?, ?)",
            [(fetched_at, p["source_date"], p["metal"], p["unit"], p["price_npr"]) for p in prices],
        )

    for p in prices:
        logger.info("%s: Rs %s / %s (as of %s)", p["metal"], f"{p['price_npr']:,}", p["unit"], p["source_date"])
    return 0


def cmd_latest(_args) -> int:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metal_prices
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM metal_prices)
            ORDER BY metal
            """
        ).fetchall()
    if not rows:
        logger.error("No prices stored yet. Run 'python prices.py fetch' first.")
        return 1
    for row in rows:
        print(f"{row['metal']}: Rs {row['price_npr']:,} / {row['unit']}  (source date: {row['source_date']})")
    return 0


def get_latest_prices():
    """Importable helper for other scripts (e.g. a future widget integration)."""
    init_db()
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM metal_prices
            WHERE fetched_at = (SELECT MAX(fetched_at) FROM metal_prices)
            ORDER BY metal
            """
        ).fetchall()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nepal gold & silver price tracker (NPR/tola).")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("fetch", help="Fetch today's rates and store them.").set_defaults(func=cmd_fetch)
    sub.add_parser("latest", help="Print the most recently stored rates.").set_defaults(func=cmd_latest)
    parser.set_defaults(func=cmd_fetch)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
