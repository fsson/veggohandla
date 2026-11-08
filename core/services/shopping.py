"""The shopping list is computed from the week plan on every view.

Only the user's changes are stored ("already at home", extra products, chosen products).
The list can therefore never get out of sync with the plan: change the plan and the list changes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext, gettext_lazy, pgettext_lazy

from core.domain.aggregate import AggregatedItem, Line, aggregate, scale
from core.domain.units import MASS, conversion_factor, to_base
from core.models import (
    Category,
    ExtraItem,
    Ingredient,
    PlannedMeal,
    Recipe,
    Retailer,
    ShoppingItemState,
)
from core.services import catalog
from core.services.catalog import Offer

# Lazy, so they follow the language active when they are rendered.
WEEKDAYS = [
    gettext_lazy("Måndag"), gettext_lazy("Tisdag"), gettext_lazy("Onsdag"), gettext_lazy("Torsdag"),
    gettext_lazy("Fredag"), gettext_lazy("Lördag"), gettext_lazy("Söndag"),
]
WEEKDAYS_SHORT = [
    pgettext_lazy("weekday abbreviation", "Mån"), pgettext_lazy("weekday abbreviation", "Tis"),
    pgettext_lazy("weekday abbreviation", "Ons"), pgettext_lazy("weekday abbreviation", "Tor"),
    pgettext_lazy("weekday abbreviation", "Fre"), pgettext_lazy("weekday abbreviation", "Lör"),
    pgettext_lazy("weekday abbreviation", "Sön"),
]


@dataclass
class Source:
    meal_id: int
    recipe_id: int
    recipe_name: str
    day: str


@dataclass
class Row:
    key: str
    name: str
    quantity: str = ""  # the need according to the recipes: "750 g"
    sources: list[Source] = field(default_factory=list)
    ingredient_id: int | None = None
    extra_id: int | None = None
    offer: Offer | None = None
    chosen: bool = False  # the product was chosen by the user (otherwise cheapest automatically)
    options: int = 0  # number of matching products
    other: Offer | None = None  # the same product at the other chain

    @property
    def cost(self) -> Decimal | None:
        return self.offer.cost if self.offer else None


@dataclass
class Group:
    name: str
    icon: str
    rows: list[Row] = field(default_factory=list)


@dataclass
class ShoppingList:
    week: dt.date
    retailer: str
    groups: list[Group]
    staples: list[Row]
    removed: list[Row]

    @property
    def all_rows(self) -> list[Row]:
        return [r for g in self.groups for r in g.rows]

    @property
    def count(self) -> int:
        return len(self.all_rows)

    @property
    def total(self) -> Decimal:
        return sum((r.cost for r in self.all_rows if r.cost), Decimal(0))

    @property
    def missing(self) -> list[Row]:
        return [r for r in self.all_rows if r.offer is None or r.cost is None]

    @property
    def retailer_label(self) -> str:
        return Retailer(self.retailer).label

    @property
    def other_label(self) -> str:
        return Retailer(other_retailer(self.retailer)).label

    @property
    def comparison(self) -> tuple[Decimal, Decimal, int] | None:
        """(here, there, count) over products priced at both chains."""
        rows = [r for r in self.all_rows if r.cost and r.other and r.other.cost]
        if not rows:
            return None
        return (sum((r.cost for r in rows), Decimal(0)),
                sum((r.other.cost for r in rows), Decimal(0)), len(rows))

    def as_text(self) -> str:
        out = [gettext("Inköpslista v. %(week)s") % {"week": self.week.isocalendar().week}]
        for g in self.groups:
            out.append(f"\n{g.name}")
            for r in g.rows:
                if r.offer:
                    out.append(f"- {r.name}: {r.offer.amount_text} {r.offer.product.title}".rstrip())
                else:
                    out.append(f"- {r.name}" + (f" – {r.quantity}" if r.quantity else ""))
        if self.staples:
            out.append("\n" + gettext("Kolla hemma"))
            out += [f"- {r.name}" for r in self.staples]
        return "\n".join(out)


def other_retailer(retailer: str) -> str:
    return next(r for r in Retailer.values if r != retailer)


def meals_for_week(week: dt.date):
    return (
        PlannedMeal.objects.filter(date__gte=week, date__lt=week + dt.timedelta(days=7))
        .select_related("recipe")
        .prefetch_related("recipe__ingredients")
    )


def _item_row(ing: Ingredient, item: AggregatedItem, retailer: str) -> Row:
    ranked = catalog.offers(ing, item, retailer)
    chosen, by_user = catalog.choose(ing, item, retailer, ranked)
    other = None
    if chosen:
        other = catalog.offer(ing, chosen.product, item, other_retailer(retailer))
    return Row(
        key=f"i{ing.pk}",
        name=ing.name,
        quantity=item.display(),
        ingredient_id=ing.pk,
        offer=chosen,
        chosen=by_user,
        options=len(ranked),
        other=other,
    )


def build(week: dt.date, retailer: str) -> ShoppingList:
    meals = list(meals_for_week(week))
    lines: list[Line] = []
    sources: dict[int, Source] = {}
    for meal in meals:
        sources[meal.id] = Source(meal.id, meal.recipe_id, meal.recipe.name, WEEKDAYS_SHORT[meal.date.weekday()])
        for ri in meal.recipe.ingredients.all():
            lines.append(Line(ri.ingredient_id, scale(ri.quantity, meal.recipe.servings, meal.servings),
                              ri.unit, meal.id))

    ingredients = Ingredient.objects.select_related("category").in_bulk({ln.ingredient_id for ln in lines})
    items = aggregate(lines, {i: ing.facts() for i, ing in ingredients.items()})
    states = {s.ingredient_id: s for s in ShoppingItemState.objects.filter(week=week)}

    # Section names are stored in Swedish; gettext maps them to the active language
    # (the names are marked for extraction in seed_data.py).
    groups: dict[int, Group] = {c.id: Group(gettext(c.name), c.icon) for c in Category.objects.all()}
    staples: list[Row] = []
    removed: list[Row] = []

    for ing_id, item in sorted(items.items(), key=lambda kv: ingredients[kv[0]].name):
        ing = ingredients[ing_id]
        if not ing.in_shopping_list:
            continue
        state = states.get(ing_id)
        if ing.is_staple:
            row = Row(key=f"i{ing_id}", name=ing.name, quantity=item.display(), ingredient_id=ing_id)
        else:
            row = _item_row(ing, item, retailer)
        row.sources = [sources[s] for s in item.sources]
        if state and state.removed:
            removed.append(row)
            continue
        (staples if ing.is_staple else groups[ing.category_id].rows).append(row)

    ordered = [g for g in groups.values() if g.rows]
    extras = list(ExtraItem.objects.filter(week=week).select_related("product"))
    if extras:
        group = Group(gettext("Extra varor"), "➕")
        for x in extras:
            group.rows.append(_extra_row(x, retailer))
        ordered.append(group)
    return ShoppingList(week, retailer, ordered, staples, removed)


def _extra_row(x: ExtraItem, retailer: str) -> Row:
    def make(r: str) -> Offer | None:
        price = catalog.price_at(x.product, r)
        if price is None:
            return None
        return Offer(x.product, price, x.count, (x.count * price.unit_price(x.count)).quantize(Decimal("0.01")), True)

    return Row(key=f"x{x.pk}", name=x.product.name, quantity=f"{x.count} st",
               extra_id=x.pk, offer=make(retailer), other=make(other_retailer(retailer)), chosen=True)


# ------------------------------------------------------------------ recipe cost


def consumed_cost(quantity: Decimal | None, unit: str, ingredient: Ingredient, offer: Offer) -> Decimal | None:
    """Cost of exactly the amount used (not the whole package).

    E.g. 200 g pasta from a 500 g package costing 20 kr = 8 kr.
    """
    price = offer.price.unit_price()
    product = offer.product
    if quantity is None or price is None:
        return None
    facts = ingredient.facts(product)
    amount, dim = to_base(quantity, unit)
    if product.price_per_kg:
        f = conversion_factor(dim, MASS, facts)
        return None if f is None else (amount * f / 1000 * price).quantize(Decimal("0.01"))
    buy = facts.buy_unit()
    if buy is None:
        return None
    f = conversion_factor(dim, buy[1], facts)
    return None if f is None else (amount * f / buy[0] * price).quantize(Decimal("0.01"))


@dataclass
class RecipeLine:
    text: str
    ingredient: Ingredient
    offer: Offer | None
    cost: Decimal | None


def recipe_lines(recipe: Recipe, factor: Decimal, retailer: str) -> tuple[list[RecipeLine], Decimal | None]:
    """The recipe's lines with chosen product and consumed cost, plus the total."""
    out: list[RecipeLine] = []
    total, priced = Decimal(0), 0
    for ri in recipe.ingredients.select_related("ingredient__category"):
        ing = ri.ingredient
        o = cost = None
        if ing.in_shopping_list and not ing.is_staple:
            qty = ri.quantity * factor if ri.quantity is not None else None
            item = aggregate([Line(ing.pk, qty, ri.unit)], {ing.pk: ing.facts()}).get(ing.pk)
            o, _ = catalog.choose(ing, item, retailer)
            if o:
                cost = consumed_cost(qty, ri.unit, ing, o)
                if cost is not None:
                    total += cost
                    priced += 1
        out.append(RecipeLine(ri.as_text(factor), ing, o, cost))
    return out, (total if priced else None)
