"""From ingredient to product: which products in the index "are" an ingredient, and which
of them is the best buy for the amount needed.

Product matching (Ingredient.match) is an explicit rule, not a guess:

    "krossade tomat"                 all words must be present (at the start of a word in the product name)
    "spenat baby; babyspenat"        ; separates alternatives (one match is enough)
    "lök gul -syltad -stekt"         -word excludes
    "tortilla @brod-och-kakor"       @ restricts to a store category (prefix)

Without @ the store categories of the ingredient's section are used. Without a rule
the name is used. Only products vetted as vegan and priced at the chain are included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Prefetch, Q, QuerySet
from django.utils.translation import gettext

from core.domain.aggregate import AggregatedItem, merge_with
from core.domain.units import MASS, conversion_factor, format_quantity
from core.models import Ingredient, Price, Product
from core.services.index import normalize

MAX_CANDIDATES = 60


@dataclass
class Alternative:
    words: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


def parse_match(text: str) -> list[Alternative]:
    alts = []
    for part in (text or "").split(";"):
        alt = Alternative()
        for token in part.split():
            if token.startswith("@"):
                alt.categories.append(token[1:])
            elif token.startswith("-") and len(token) > 1:
                alt.excludes.append(normalize(token[1:]))
            else:
                w = normalize(token)
                if w:
                    alt.words.append(w)
        if alt.words:
            alts.append(alt)
    return alts


def _word(w: str) -> Q:
    return Q(search_text__regex=r"(^| )" + re.escape(w))


def match_q(ingredient: Ingredient) -> Q | None:
    rule = ingredient.match or ingredient.name
    default_cats = (ingredient.category.store_categories or "").split()
    combined = Q()
    any_alt = False
    for alt in parse_match(rule):
        q = Q()
        for w in alt.words:
            q &= _word(w)
        for w in alt.excludes:
            q &= ~_word(w)
        cats = alt.categories or default_cats
        if cats:
            cq = Q()
            for c in cats:
                cq |= Q(category__startswith=c)
            q &= cq
        combined |= q
        any_alt = True
    return combined if any_alt else None


def vegan_products(retailer: str | None = None) -> QuerySet[Product]:
    qs = Product.objects.filter(vegan=True)
    if retailer:
        qs = qs.filter(prices__retailer=retailer, prices__price__isnull=False)
    return qs.prefetch_related(Prefetch("prices", to_attr="price_list"))


def candidates(ingredient: Ingredient, retailer: str) -> list[Product]:
    q = match_q(ingredient)
    if q is None:
        return []
    return list(vegan_products(retailer).filter(q).distinct()[:MAX_CANDIDATES])


def price_at(product: Product, retailer: str) -> Price | None:
    prices = getattr(product, "price_list", None)
    if prices is None:
        prices = list(product.prices.all())
    return next((p for p in prices if p.retailer == retailer and p.price is not None), None)


# ---------------------------------------------------------------- offers


@dataclass
class Offer:
    """What it costs to cover the need with a certain product."""

    product: Product
    price: Price
    packages: int | None  # None = loose weight
    cost: Decimal | None  # None = can't be calculated (unknown conversion)
    exact: bool  # False = the need couldn't be converted to the product's size
    kg: Decimal | None = None

    @property
    def promo(self) -> bool:
        return self.price.promo_active() and (self.packages or 1) >= self.price.promo_min

    @property
    def amount_text(self) -> str:
        if self.product.price_per_kg:
            if self.kg:
                return gettext("ca %(amount)s") % {"amount": format_quantity(self.kg * 1000, MASS)}
            return gettext("lösvikt")
        return f"{self.packages} st" if self.packages else ""


def _ore(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def offer(ingredient: Ingredient, product: Product, item: AggregatedItem | None, retailer: str) -> Offer | None:
    price = price_at(product, retailer)
    if price is None:
        return None
    facts = ingredient.facts(product)
    need = merge_with(item, facts) if item and item.amounts else None
    if product.price_per_kg:
        if need and len(need.amounts) == 1:
            (dim, amount), = need.amounts.items()
            f = conversion_factor(dim, MASS, facts)
            if f is not None:
                kg = amount * f / 1000
                return Offer(product, price, None, _ore(kg * price.unit_price()), True, kg)
        return Offer(product, price, None, None, False)
    packages = need.packages if need else None
    exact = packages is not None
    packages = packages or 1
    return Offer(product, price, packages, _ore(packages * price.unit_price(packages)), exact)


def _rank(o: Offer) -> tuple:
    # Calculable first, then cheapest; on a tie: least waste (fewest packages),
    # then shortest name (the "plain" variant before flavoured ones).
    return (not o.exact, o.cost is None, o.cost or Decimal(0), o.packages or 0,
            len(o.product.search_text.split()), o.product.name)


def offers(ingredient: Ingredient, item: AggregatedItem | None, retailer: str,
           products: list[Product] | None = None) -> list[Offer]:
    products = candidates(ingredient, retailer) if products is None else products
    found = [o for p in products if (o := offer(ingredient, p, item, retailer))]
    return sorted(found, key=_rank)


def choose(ingredient: Ingredient, item: AggregatedItem | None, retailer: str,
           ranked: list[Offer] | None = None) -> tuple[Offer | None, bool]:
    """(chosen product, chosen by the user?). The user's choice applies if the chain stocks the product."""
    ranked = offers(ingredient, item, retailer) if ranked is None else ranked
    if ingredient.preferred_code:
        mine = next((o for o in ranked if o.product.code == ingredient.preferred_code), None)
        if mine is None:
            p = vegan_products(retailer).filter(code=ingredient.preferred_code).first()
            mine = offer(ingredient, p, item, retailer) if p else None
        if mine:
            return mine, True
    return (ranked[0] if ranked else None), False


@dataclass
class CategoryNode:
    slug: str  # "skafferi" or "skafferi/asien"
    name: str  # "Skafferi" or "Asien"
    count: int = 0
    children: list[CategoryNode] = field(default_factory=list)


def category_tree(retailer: str) -> list[CategoryNode]:
    """The store's categories as a tree (top -> sub) with the number of priced vegan products."""
    from django.db.models import Count

    rows = (Product.objects.filter(vegan=True, prices__retailer=retailer, prices__price__isnull=False)
            .values("category", "category_name").annotate(n=Count("id", distinct=True))
            .order_by("category_name"))
    tops: dict[str, CategoryNode] = {}
    for r in rows:
        top_slug = r["category"].split("/")[0]
        top_name, _, sub_name = r["category_name"].partition(" › ")
        top = tops.setdefault(top_slug, CategoryNode(top_slug, top_name))
        top.children.append(CategoryNode(r["category"], sub_name or top_name, r["n"]))
        top.count += r["n"]
    return list(tops.values())


def search(query: str, retailer: str, limit: int = 40) -> list[Product]:
    """Free-text search in the vegan index (all words, at the start of words)."""
    words = normalize(query).split()
    if not words:
        return []
    q = Q()
    for w in words:
        q &= _word(w) | Q(brand__icontains=w)
    return list(vegan_products(retailer).filter(q).distinct().order_by("name")[:limit])
