"""Products and prices from Axfood's chains (Willys, Hemköp).

Uses the same open JSON calls as the chains' own websites. This is not an official
API: it can change without notice and the chains' terms apply (the content may only
be used for personal use). Therefore:
  * requests are only made while indexing, for the user's own local app,
  * the chains' robots.txt is followed: at most one request per 10 seconds per chain,
    and only between 04:00 and 08:45 UTC ("Crawl-delay" and "Visit-time"),
  * everything is stored locally – the app keeps working when the chains don't respond.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

BASE_URLS = {
    "willys": "https://www.willys.se",
    "hemkop": "https://www.hemkop.se",
}
USER_AGENT = "Veggohandla/0.2 (personal meal planner; low-frequency requests)"
TIMEOUT = 15.0
# What the chains ask for in robots.txt.
CRAWL_DELAY = 10.0  # seconds between requests to the same chain ("Crawl-delay: 10")
# "Visit-time: 0400-0845" (UTC): no fetching outside this window.
VISIT_START = dt.time(4, 0)
VISIT_END = dt.time(8, 45)
PAGE_SIZE = 100  # largest page size the chains respond with

_locks = {r: threading.Lock() for r in BASE_URLS}
_last_call = {r: 0.0 for r in BASE_URLS}


class StoreError(Exception):
    """The store did not respond as expected."""


class OutsideVisitTime(Exception):
    """The chains ask to only be visited 04:00–08:45 UTC."""


def in_visit_time(now: dt.datetime | None = None) -> bool:
    """May we fetch right now (within the chains' visiting hours)?"""
    t = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).time()
    return VISIT_START <= t < VISIT_END


def visit_window(day: dt.date | None = None) -> tuple[dt.datetime, dt.datetime]:
    """The visiting hours on a given (UTC) day, as UTC datetimes."""
    day = day or dt.datetime.now(dt.UTC).date()
    return (dt.datetime.combine(day, VISIT_START, tzinfo=dt.UTC), dt.datetime.combine(day, VISIT_END, tzinfo=dt.UTC))


def next_visit_time(now: dt.datetime | None = None) -> dt.datetime:
    """Next time (UTC) at which fetching is allowed."""
    now = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    if in_visit_time(now):
        return now
    start = now.replace(hour=VISIT_START.hour, minute=VISIT_START.minute, second=0, microsecond=0)
    return start if now < start else start + dt.timedelta(days=1)


@dataclass
class ProductData:
    """A product as it appears in a category listing (price, size, promotion)."""

    retailer: str
    code: str
    name: str
    brand: str = ""
    size_text: str = ""
    size_amount: Decimal | None = None
    size_unit: str = ""
    price: Decimal | None = None
    price_per_kg: bool = False
    compare_price: str = ""
    promo_price: Decimal | None = None
    promo_min: int = 1
    promo_text: str = ""
    promo_until: dt.date | None = None
    image_url: str = ""


@dataclass
class Details:
    """What is only available on the product's own page."""

    ean: str
    ingredients: str
    diet: str


def product_url(retailer: str, code: str, name: str = "") -> str:
    """Public product page; the name slug is cosmetic but matches the chains' own links."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-")
    return f"{BASE_URLS[retailer]}/produkt/{slug + '-' if slug else ''}{code}"


def _get(retailer: str, path: str, params: dict | None = None) -> dict:
    if retailer not in BASE_URLS:
        raise StoreError(f"Okänd kedja: {retailer}")
    if not in_visit_time():
        raise OutsideVisitTime()
    with _locks[retailer]:
        wait = CRAWL_DELAY - (time.monotonic() - _last_call[retailer])
        if wait > 0:
            time.sleep(wait)
        _last_call[retailer] = time.monotonic()
        try:
            r = httpx.get(
                BASE_URLS[retailer] + path,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=TIMEOUT,
                follow_redirects=True,
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise StoreError(f"Kunde inte hämta från {retailer}: {e}") from e


# ------------------------------------------------------------------ parsing

_SIZE_RE = re.compile(
    # "400/240g" = net weight/drained weight on canned goods: the net weight counts.
    r"(?:(?P<n>\d+)\s*[x×]\s*)?(?P<amount>\d+(?:[.,]\d+)?)(?:/\d+(?:[.,]\d+)?)?\s*(?P<unit>kg|g|l|dl|cl|ml|st|p)\b",
    re.IGNORECASE,
)
_SIZE_FACTORS = {
    "kg": ("g", 1000),
    "g": ("g", 1),
    "l": ("ml", 1000),
    "dl": ("ml", 100),
    "cl": ("ml", 10),
    "ml": ("ml", 1),
    "st": ("st", 1),
    "p": ("st", 1),
}


def parse_size(text: str) -> tuple[Decimal | None, str]:
    """'300g' -> (300, 'g'), '1,5l' -> (1500, 'ml'), '4x125g' -> (500, 'g'), 'ca: 1kg' -> (1000, 'g'),
    '380/230g' -> (380, 'g')."""
    m = _SIZE_RE.search(text or "")
    if not m:
        return None, ""
    try:
        amount = Decimal(m.group("amount").replace(",", "."))
    except InvalidOperation:
        return None, ""
    unit, factor = _SIZE_FACTORS[m.group("unit").lower()]
    amount *= factor
    if m.group("n"):
        amount *= int(m.group("n"))
    if amount <= 0:
        return None, ""
    return amount, unit


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def parse_listing_item(retailer: str, d: dict) -> ProductData:
    size_text = d.get("displayVolume") or ""
    size_amount, size_unit = parse_size(size_text)
    price_per_kg = (d.get("priceUnit") or "").lower().endswith("/kg")
    if price_per_kg:
        size_amount, size_unit = Decimal(1000), "g"

    promo_price = promo_until = None
    promo_min, promo_text = 1, ""
    promos = d.get("potentialPromotions") or []
    if promos:
        p = promos[0]
        # price.value is the per-unit price under a promotion ("2 för 46" -> 23 kr each when buying 2).
        promo_price = _dec((p.get("price") or {}).get("value"))
        if promo_price is not None:
            promo_price = promo_price.quantize(Decimal("0.01"))
        promo_min = max(1, int(p.get("qualifyingCount") or 1))
        label = " ".join(x for x in (p.get("conditionLabel"), p.get("rewardLabel")) if x)
        promo_text = (label or "Kampanj")[:80]
        if p.get("validUntil"):
            promo_until = dt.datetime.fromtimestamp(p["validUntil"] / 1000).date()

    compare = d.get("comparePrice") or ""
    if compare and d.get("comparePriceUnit"):
        compare += "/" + d["comparePriceUnit"]
    image = (d.get("image") or {}).get("url") or (d.get("thumbnail") or {}).get("url") or ""
    return ProductData(
        retailer=retailer,
        code=d["code"],
        name=(d.get("name") or "").strip(),
        brand=(d.get("manufacturer") or "").strip(),
        size_text=size_text,
        size_amount=size_amount,
        size_unit=size_unit,
        price=_dec(d.get("priceValue")),
        price_per_kg=price_per_kg,
        compare_price=compare,
        promo_price=promo_price,
        promo_min=promo_min,
        promo_text=promo_text,
        promo_until=promo_until,
        image_url=image,
    )


# ------------------------------------------------------------------ public API


def category_tree(retailer: str) -> list[dict]:
    """Top categories with subcategories: [{"url", "title", "children": [...]}, ...]."""
    return _get(retailer, "/leftMenu/categorytree").get("children") or []


def list_category(retailer: str, slug: str) -> Iterator[ProductData]:
    """All products in a category, page by page."""
    page = 0
    while True:
        data = _get(retailer, f"/c/{slug}", {"size": PAGE_SIZE, "page": page})
        for item in data.get("results") or []:
            if item.get("code") and item.get("name"):
                yield parse_listing_item(retailer, item)
        pages = (data.get("pagination") or {}).get("numberOfPages") or 0
        page += 1
        if page >= pages:
            return


def fetch_details(retailer: str, code: str) -> Details:
    if not re.fullmatch(r"[\w-]+", code):
        raise StoreError("Ogiltig artikelkod")
    d = _get(retailer, f"/axfood/rest/p/{code}")
    return Details(
        ean=d.get("ean") or "",
        ingredients=(d.get("ingredients") or "").strip(),
        diet=d.get("dietTypeInformation") or "",
    )
