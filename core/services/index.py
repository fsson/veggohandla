"""Local index of the chains' range.

One run (the chains' robots.txt: one request per 10 s, only 04:00–08:45 UTC):
  1. Willys category listings  -> Product + Price(willys)   (a few hundred requests ≈ an hour)
  2. Hemköp category listings  -> Price(hemkop) for the same article codes (a few hundred requests ≈ an hour)
  3. The product page for products not yet vetted -> ingredient list + vegan?
     Once per product: the first time many thousands of requests, i.e. up to a week of mornings.
     Products matching an ingredient are vetted first, so the shopping list works right away.

When the time window closes the run pauses. Everything fetched is saved and the next run
continues where this one stopped (the listings are skipped if they were fetched today).

Runs are started by the scheduler in `manage.py serve` (every morning), by the "update now"
button, or by `manage.py index`. Only one run at a time: a run claims the index in the
database and keeps a heartbeat, so a run in another process is seen too.

Willys is the "catalogue" (categories, ingredients). Hemköp is used for price comparison
on the same article codes – the chains share article codes since both are owned by Axfood.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import threading
from collections.abc import Callable

from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from core.domain.vegan import classify
from core.models import AppSettings, Price, Product, Retailer
from core.stores import axfood
from core.stores.axfood import StoreError

log = logging.getLogger(__name__)

# Which categories to crawl: None = everything except the top categories that are meat, fish or
# non-food (SKIPPED_TOP_WORDS). Dairy, frozen, ready meals, drinks, sweets and so on are crawled
# whole, because vegan products hide in all of them (vegan cheese, ice cream, pizza ...); the vegan
# check keeps only what is actually vegan. A dict {top slug: [subcategories] or None} restricts it.
WILLYS_SECTIONS: dict[str, list[str] | None] | None = None
HEMKOP_SECTIONS: dict[str, list[str] | None] | None = None
# Words in a top category's slug that mark it as never vegan or not food.
SKIPPED_TOP_WORDS = (
    "kott",
    "fisk",
    "fagel",
    "chark",
    "skaldjur",  # animal products
    "hushall",
    "hygien",
    "apotek",
    "skonhet",
    "kosmetik",
    "djur",
    "blommor",
    "tobak",
    "tvatt",
    "barnvard",  # non-food
)

RECHECK_AFTER = dt.timedelta(days=120)  # ingredient lists rarely change
RECHECK_PER_RUN = 300
MAX_ERRORS = 8
# A run that has been silent this long counts as aborted (e.g. the process was killed). The
# heartbeat is written for every request, i.e. at least every ~10 s while a run is alive.
HEARTBEAT_TIMEOUT = dt.timedelta(minutes=10)

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()

Progress = Callable[[str], None]


_FOLD = str.maketrans("éèêëáàâíìîóòôúùûüñç", "eeeeaaaiiiooouuuunc")


def normalize(text: str) -> str:
    """'Tomater Krossade 3-pack' -> 'tomater krossade 3 pack', 'Fraîche' -> 'fraiche'. Å, ä, ö are kept."""
    return " ".join(re.findall(r"[^\W_]+", (text or "").lower().translate(_FOLD)))


def resolve_sections(tree: list[dict], sections: dict[str, list[str] | None] | None) -> list[tuple[str, str]]:
    """[(path, 'Top › Sub'), ...] for the selected subcategories."""
    out = []
    for top in tree:
        top_slug = top.get("url", "")
        if sections is None:
            if any(w in top_slug for w in SKIPPED_TOP_WORDS):
                log.info("Index: skipping category %s", top_slug)
                continue
            wanted = None
        elif top_slug in sections:
            wanted = sections[top_slug]
        else:
            continue
        for child in top.get("children") or []:
            slug = child.get("url", "")
            if wanted is None or slug.rsplit("/", 1)[-1] in wanted:
                out.append((slug, f"{top.get('title', '')} › {child.get('title', '')}"))
    return out


def _save_price(product: Product, pd: axfood.ProductData, now) -> None:
    Price.objects.update_or_create(
        product=product,
        retailer=pd.retailer,
        defaults=dict(
            price=pd.price,
            compare_price=pd.compare_price,
            promo_price=pd.promo_price,
            promo_min=pd.promo_min,
            promo_text=pd.promo_text,
            promo_until=pd.promo_until,
            seen_at=now,
        ),
    )


def _upsert_product(pd: axfood.ProductData, category: str, category_name: str, now) -> Product:
    product, created = Product.objects.get_or_create(
        code=pd.code, defaults={"category": category, "category_name": category_name}
    )
    product.name = pd.name
    product.brand = pd.brand
    product.size_text = pd.size_text
    product.size_amount = pd.size_amount
    product.size_unit = pd.size_unit
    product.price_per_kg = pd.price_per_kg
    product.image_url = pd.image_url
    product.search_text = normalize(pd.name)[:300]
    product.seen_at = now
    if created or not product.category:
        product.category, product.category_name = category, category_name
    product.save()
    return product


def apply_details(product: Product, details: axfood.Details) -> None:
    product.ean = details.ean[:14]
    product.ingredients = details.ingredients
    product.diet = details.diet[:80]
    product.checked_at = timezone.now()
    product.vegan, product.vegan_reason = classify(product.diet, product.ingredients, product.category, product.name)
    product.save()


def reclassify() -> int:
    """Re-run the vegan check on stored ingredient lists (no network requests)."""
    changed = 0
    for p in Product.objects.filter(checked_at__isnull=False).iterator():
        vegan, reason = classify(p.diet, p.ingredients, p.category, p.name)
        if (vegan, reason) != (p.vegan, p.vegan_reason):
            Product.objects.filter(pk=p.pk).update(vegan=vegan, vegan_reason=reason)
            changed += 1
    return changed


def _set_progress(text: str, progress: Progress | None = None) -> None:
    """Store a progress message and report it to a console callback."""
    AppSettings.objects.filter(pk=1).update(index_progress=text, index_heartbeat=timezone.now())
    if progress:
        progress(text)


def _finish(text: str) -> str:
    """Store the final summary of a run and return it."""
    AppSettings.objects.filter(pk=1).update(index_progress=text)
    return text


class AlreadyRunning(Exception):
    """Another index run holds the index."""


def listings_fresh(settings: AppSettings, now: dt.datetime) -> bool:
    """Were the category listings (prices) fetched today (UTC)? The visiting hours are a
    single UTC morning, so "today" means "in this morning's window"."""
    return bool(settings.listed_at and settings.listed_at.astimezone(dt.UTC).date() == now.astimezone(dt.UTC).date())


def has_pending_work(now: dt.datetime | None = None) -> bool:
    """Is there anything for a run to do: today's prices, or products still to be vetted?"""
    now = now or timezone.now()
    settings = AppSettings.load()
    if not listings_fresh(settings, now):
        return True
    return Product.objects.filter(seen_at__gte=settings.listed_at, checked_at__isnull=True).exists()


def _claim(now: dt.datetime) -> bool:
    """Atomically mark the index as running, unless a live run already holds it."""
    AppSettings.load()
    free = Q(index_running=False) | Q(index_heartbeat__isnull=True) | Q(index_heartbeat__lt=now - HEARTBEAT_TIMEOUT)
    return AppSettings.objects.filter(free, pk=1).update(index_running=True, index_error="", index_heartbeat=now) == 1


def _crawl(retailer: str, sections, now, progress, only_known: bool) -> tuple[int, int]:
    """Go through a chain's categories. Returns (number of products, number of errors)."""
    errors = 0
    count = 0
    tree = axfood.category_tree(retailer)
    slugs = resolve_sections(tree, sections)
    known = set(Product.objects.values_list("code", flat=True)) if only_known else set()
    for i, (slug, name) in enumerate(slugs, 1):
        _set_progress(f"{Retailer(retailer).label}: {name} ({i}/{len(slugs)})", progress)
        try:
            # Fetch first, write afterwards: the pages of a category take 10 s each, and the
            # database must not be locked for the web app while we wait.
            items = list(axfood.list_category(retailer, slug))
            with transaction.atomic():
                for pd in items:
                    if only_known:
                        if pd.code not in known:
                            continue
                        product = Product.objects.get(code=pd.code)
                        if product.price_per_kg != pd.price_per_kg:
                            continue  # sold differently (per piece/per kg) – not comparable
                    else:
                        product = _upsert_product(pd, slug, name, now)
                    _save_price(product, pd, now)
                    count += 1
        except StoreError as e:
            errors += 1
            log.warning("Index: %s", e)
            if errors >= MAX_ERRORS:
                raise
    return count, errors


def _matching_ingredients_first(pks: list[int]) -> list[int]:
    """Products matching some ingredient first – they are needed in the shopping list."""
    from core.models import Ingredient
    from core.services.catalog import match_q

    wanted: set[int] = set()
    for ing in Ingredient.objects.select_related("category").filter(in_shopping_list=True):
        q = match_q(ing)
        if q is not None:
            wanted.update(Product.objects.filter(q, pk__in=pks).values_list("pk", flat=True))
    return [pk for pk in pks if pk in wanted] + [pk for pk in pks if pk not in wanted]


def run(progress: Progress | None = None, details: bool = True, force_listings: bool = False) -> str:
    """One index run. Returns a summary. Pauses when the time window closes.

    Raises OutsideVisitTime outside the chains' visiting hours and AlreadyRunning if another
    run holds the index.
    """
    if not axfood.in_visit_time():
        raise axfood.OutsideVisitTime()
    now = timezone.now()
    if not _claim(now):
        raise AlreadyRunning()
    settings = AppSettings.load()
    n_w = n_h = checked = 0
    try:
        reclassify()
        if listings_fresh(settings, now) and not force_listings:
            listed = settings.listed_at
            _set_progress("Listningarna är färska – fortsätter granskningen", progress)
        else:
            n_w, err_w = _crawl("willys", WILLYS_SECTIONS, now, progress, only_known=False)
            if not err_w:
                Price.objects.filter(retailer="willys", seen_at__lt=now).delete()
            n_h, err_h = _crawl("hemkop", HEMKOP_SECTIONS, now, progress, only_known=True)
            if not err_h:
                Price.objects.filter(retailer="hemkop", seen_at__lt=now).delete()
            listed = now
            AppSettings.objects.filter(pk=1).update(listed_at=now)

        if details:
            current = Product.objects.filter(seen_at__gte=listed)
            todo = _matching_ingredients_first(
                list(current.filter(checked_at__isnull=True).values_list("pk", flat=True))
            )
            todo += list(
                current.filter(checked_at__lt=now - RECHECK_AFTER)
                .order_by("checked_at")
                .values_list("pk", flat=True)[:RECHECK_PER_RUN]
            )
            errors = 0
            for i, pk in enumerate(todo, 1):
                product = Product.objects.get(pk=pk)
                _set_progress(f"Granskar ingredienser: {i} av {len(todo)}", progress if i == 1 or i % 25 == 0 else None)
                try:
                    apply_details(product, axfood.fetch_details("willys", product.code))
                    checked += 1
                except StoreError as e:
                    errors += 1
                    log.warning("Index: %s", e)
                    if errors >= MAX_ERRORS:
                        raise
        vegan = Product.objects.filter(vegan=True, seen_at__gte=listed).count()
        AppSettings.objects.filter(pk=1).update(indexed_at=timezone.now())
        return _finish(f"{n_w} varor hos Willys, {n_h} med pris hos Hemköp, {checked} granskade, {vegan} veganska.")
    except axfood.OutsideVisitTime:
        left = Product.objects.filter(checked_at__isnull=True).count()
        return _finish(
            f"Pausad: kedjornas tidsfönster stängde. {checked} granskade nu, {left} kvar – fortsätter nästa körning."
        )
    except StoreError as e:
        AppSettings.objects.filter(pk=1).update(index_error=str(e)[:300])
        raise
    finally:
        AppSettings.objects.filter(pk=1).update(index_running=False)


def is_running() -> bool:
    """Is a run in progress – in this process or another (e.g. `manage.py index`)?"""
    if _thread and _thread.is_alive():
        return True
    s = AppSettings.objects.filter(pk=1).values("index_running", "index_heartbeat").first()
    return bool(
        s and s["index_running"] and s["index_heartbeat"] and timezone.now() - s["index_heartbeat"] < HEARTBEAT_TIMEOUT
    )


def start_background() -> bool:
    """Start an index run in a background thread (from the web app). False if one is already running."""
    global _thread
    with _thread_lock:
        if is_running() or not axfood.in_visit_time():
            return False

        def work():
            try:
                run()
            except (axfood.OutsideVisitTime, AlreadyRunning):
                pass
            except Exception as e:  # noqa: BLE001 – the thread must never die silently
                log.exception("Indexeringen misslyckades")
                AppSettings.objects.filter(pk=1).update(index_error=str(e)[:300], index_running=False)
            finally:
                close_old_connections()

        _thread = threading.Thread(target=work, name="veggohandla-index", daemon=True)
        _thread.start()
        return True
