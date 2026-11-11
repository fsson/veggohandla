"""Aggregation of ingredients from planned meals into shopping rows.

Rules:
* Lines are merged ONLY if they point at the same ingredient id. Never by name similarity.
* Amounts in different dimensions (g, st, förp …) are merged only if the ingredient has
  known conversions. Otherwise they are shown side by side: "500 g + 2 st".
* Lines without an amount ("salt efter smak") produce a row without an amount.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from .units import (
    MASS,
    PACKAGE,
    PIECE,
    VOLUME,
    IngredientFacts,
    conversion_factor,
    dimension_of,
    format_number,
    format_quantity,
    packages_needed,
    to_base,
)

_DIM_PREFERENCE = [MASS, VOLUME, PACKAGE, PIECE]


@dataclass(frozen=True)
class Line:
    ingredient_id: int
    quantity: Decimal | None
    unit: str
    source: Hashable = None  # e.g. the planned meal's id


@dataclass
class AggregatedItem:
    ingredient_id: int
    amounts: dict[str, Decimal] = field(default_factory=dict)  # dimension -> base amount
    preferred_units: dict[str, str] = field(default_factory=dict)  # dimension -> unit
    unquantified: bool = False
    sources: list[Hashable] = field(default_factory=list)
    packages: int | None = None  # estimated number of whole packages

    def signature(self) -> str:
        """Stable text key for the amount; changes when the need changes."""
        parts = [f"{d}:{format_number(a, 3)}" for d, a in sorted(self.amounts.items())]
        if self.unquantified:
            parts.append("?")
        return "|".join(parts)

    def display(self) -> str:
        parts: list[str] = []
        for dim in sorted(self.amounts, key=_dim_rank):
            amount = self.amounts[dim]
            if dim not in (MASS, VOLUME):
                # Countable units are bought in whole numbers.
                amount = amount.to_integral_value(rounding=ROUND_CEILING) if amount > 0 else amount
            parts.append(format_quantity(amount, dim, self.preferred_units.get(dim)))
        return " + ".join(parts)


def _dim_rank(dim: str) -> int:
    return _DIM_PREFERENCE.index(dim) if dim in _DIM_PREFERENCE else len(_DIM_PREFERENCE)


def scale(quantity: Decimal | None, recipe_servings: int, planned_servings: int) -> Decimal | None:
    """Scale an amount proportionally to the number of servings."""
    if quantity is None:
        return None
    if recipe_servings <= 0:
        raise ValueError("Recipe servings must be positive")
    return quantity * Decimal(planned_servings) / Decimal(recipe_servings)


def _merge_dimensions(amounts: dict[str, Decimal], facts: IngredientFacts) -> tuple[dict[str, Decimal], set[str]]:
    """Merge dimensions that can be converted. Returns (amounts, targets that received)."""
    if len(amounts) <= 1:
        return dict(amounts), set()

    best_target, best_absorbed = None, -1
    for target in sorted(amounts, key=_dim_rank):
        absorbed = sum(1 for d in amounts if d != target and conversion_factor(d, target, facts) is not None)
        if absorbed > best_absorbed:
            best_target, best_absorbed = target, absorbed
    assert best_target is not None

    result: dict[str, Decimal] = {best_target: amounts[best_target]}
    receivers: set[str] = set()
    for dim, amount in amounts.items():
        if dim == best_target:
            continue
        f = conversion_factor(dim, best_target, facts)
        if f is None:
            result[dim] = result.get(dim, Decimal(0)) + amount
        else:
            result[best_target] += amount * f
            receivers.add(best_target)
    return result, receivers


def estimate_packages(item: AggregatedItem, facts: IngredientFacts) -> int | None:
    """Number of whole packages if it can be worked out, otherwise None."""
    if len(item.amounts) != 1:
        return None
    ((dim, amount),) = item.amounts.items()
    buy = facts.buy_unit()
    if buy is None:
        return packages_needed(amount, Decimal(1)) if dim == PACKAGE else None
    buy_amount, buy_dim = buy
    f = conversion_factor(dim, buy_dim, facts)
    if f is None:
        return packages_needed(amount, Decimal(1)) if dim == PACKAGE else None
    return packages_needed(amount * f, buy_amount)


def merge_with(item: AggregatedItem, facts: IngredientFacts) -> AggregatedItem:
    """Copy of a row recalculated with (other) facts, e.g. a certain product's size.

    "1 förp + 200 g" can only be merged once it is known that the product weighs 500 g.
    """
    amounts, _ = _merge_dimensions(item.amounts, facts)
    clone = AggregatedItem(
        item.ingredient_id, amounts, dict(item.preferred_units), item.unquantified, list(item.sources)
    )
    clone.packages = estimate_packages(clone, facts)
    return clone


def aggregate(lines: Iterable[Line], facts: dict[int, IngredientFacts] | None = None) -> dict[int, AggregatedItem]:
    facts = facts or {}
    items: dict[int, AggregatedItem] = {}
    units_seen: dict[int, dict[str, set[str]]] = {}

    for line in lines:
        item = items.setdefault(line.ingredient_id, AggregatedItem(line.ingredient_id))
        if line.source is not None and line.source not in item.sources:
            item.sources.append(line.source)
        if line.quantity is None:
            item.unquantified = True
            continue
        amount, dim = to_base(line.quantity, line.unit)
        item.amounts[dim] = item.amounts.get(dim, Decimal(0)) + amount
        units_seen.setdefault(line.ingredient_id, {}).setdefault(dim, set()).add(line.unit or "st")

    for ing_id, item in items.items():
        f = facts.get(ing_id, IngredientFacts())
        item.amounts, receivers = _merge_dimensions(item.amounts, f)
        for dim, units in units_seen.get(ing_id, {}).items():
            if dim in item.amounts and dim not in receivers and len(units) == 1:
                item.preferred_units[dim] = next(iter(units))
        if item.amounts:
            # With an amount there is no need for a separate "to taste" marker.
            item.unquantified = False
        item.packages = estimate_packages(item, f)
    return items


def facts_dimension(unit_code: str) -> str:
    """Dimension for a package size given in a unit (g, kg, l, st …)."""
    return dimension_of(unit_code)
