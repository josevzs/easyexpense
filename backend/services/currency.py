import logging

import httpx

from backend.models import ParsedData

logger = logging.getLogger("easyexpense.currency")

# In-process cache: currency -> EUR rate. Rates move slowly enough that one
# lookup per currency per worker process is plenty.
_RATE_CACHE: dict[str, float] = {}


def _fetch_eur_rate(currency: str) -> float:
    """1 unit of `currency` = <return value> EUR. Falls back to 1.0 (no
    conversion) if the rate can't be fetched, so report generation never
    hard-fails just because the FX lookup is unreachable."""
    try:
        resp = httpx.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"from": currency, "to": "EUR"},
            timeout=5.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return float(resp.json()["rates"]["EUR"])
    except Exception:
        logger.warning("Could not fetch EUR exchange rate for %s, leaving unconverted", currency)
        return 1.0


def _rate_for(currency: str) -> float:
    currency = currency.upper()
    if currency == "EUR":
        return 1.0
    if currency not in _RATE_CACHE:
        _RATE_CACHE[currency] = _fetch_eur_rate(currency)
    return _RATE_CACHE[currency]


def convert_to_eur(data: ParsedData) -> ParsedData:
    """Return a copy of `data` with every expense/allocation amount converted
    to EUR. Reports always display amounts as EUR, so this must run before
    any totals are computed — otherwise non-EUR trips silently show raw
    foreign-currency figures under a euro sign."""
    expenses = [
        e.model_copy(update={"amount": e.amount * _rate_for(e.currency), "currency": "EUR"})
        for e in data.expenses
    ]
    allocations = [
        a.model_copy(update={"share": a.share * _rate_for(a.currency), "currency": "EUR"})
        for a in data.allocations
    ]
    return data.model_copy(update={"expenses": expenses, "allocations": allocations})
