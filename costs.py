#!/usr/bin/env python3
"""Rough landed-cost helpers. Quotes are placeholders until a carrier API is wired."""

from __future__ import annotations

# Dollars per mile, open carrier, plus a floor. Sports cars should use enclosed later.
TRANSPORT_PER_MILE = 0.70
TRANSPORT_FLOOR = 650
PPI_DOLLARS = 175
SLOP_DOLLARS = 250

# Destination-state use tax as a simple rate. Refine with county later.
DEST_TAX_RATE = {
    "TN": 0.07,
    "TX": 0.0625,
    "VA": 0.043,
    "MD": 0.06,
}


def transport_estimate(miles: float) -> float:
    return max(TRANSPORT_FLOOR, miles * TRANSPORT_PER_MILE)


def dest_tax(price: float, state: str = "TN") -> float:
    return price * DEST_TAX_RATE.get(state.upper(), 0.07)


def landed_cost(ask: float, miles: float, dest_state: str = "TN") -> dict:
    truck = transport_estimate(miles)
    tax = dest_tax(ask, dest_state)
    extras = PPI_DOLLARS + SLOP_DOLLARS
    total = ask + truck + tax + extras
    return {
        "ask": ask,
        "transport": round(truck, 2),
        "tax": round(tax, 2),
        "ppi_and_slop": extras,
        "landed": round(total, 2),
    }
