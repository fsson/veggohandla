"""The ingredient page: see and change which products an ingredient matches, its aliases,
and merge duplicates ("gulcurry" created from a recipe when "Curry" already existed).

A match rule is previewed before it is saved, so the effect of every word is visible:
which vegan products it picks up, and which ones a `-word` keeps out.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models.functions import Lower

from core import seed_data
from core.models import Category, Ingredient, IngredientAlias, Product, RecipeIngredient, ShoppingItemState
from core.services import catalog
from core.services.recipes import resolve


@dataclass
class MatchPreview:
    rule: str  # the rule as used: the ingredient's name when the rule is empty
    offers: list[catalog.Offer] = field(default_factory=list)  # matched, cheapest first
    excluded: list[Product] = field(default_factory=list)  # would match, but a -word keeps them out
    capped: bool = False  # more matches than shown
    error: str = ""


def clean_rule(text: str) -> str:
    return " ".join((text or "").split())


def _without_excludes(rule: str) -> str:
    parts = [" ".join(t for t in part.split() if not (t.startswith("-") and len(t) > 1)) for part in rule.split(";")]
    return "; ".join(p for p in parts if p)


def preview(ingredient: Ingredient, rule: str, retailer: str) -> MatchPreview:
    """What `rule` would match for `ingredient`, without saving anything."""
    rule = clean_rule(rule)
    trial = copy.copy(ingredient)
    trial.match = rule
    used = rule or ingredient.name
    if not catalog.parse_match(used):
        return MatchPreview(used, error="Regeln har inga sökord – skriv minst ett ord.")
    matched = catalog.candidates(trial, retailer)
    out = MatchPreview(
        used, catalog.offers(trial, None, retailer, matched), capped=len(matched) >= catalog.MAX_CANDIDATES
    )
    if any(t.startswith("-") and len(t) > 1 for t in used.split()):
        loose = copy.copy(ingredient)
        loose.match = _without_excludes(used)
        codes = {p.code for p in matched}
        out.excluded = [p for p in catalog.candidates(loose, retailer) if p.code not in codes]
    return out


def seed_rule(ingredient: Ingredient) -> str | None:
    """The rule the seed data gives this ingredient, or None if it isn't a seed ingredient."""
    key = ingredient.name.lower()
    return next((d["match"] for d in seed_data.INGREDIENTS if d["name"].lower() == key), None)


def set_match(ingredient: Ingredient, rule: str) -> None:
    ingredient.match = clean_rule(rule)
    ingredient.match_edited = True
    ingredient.save(update_fields=["match", "match_edited"])


def reset_match(ingredient: Ingredient) -> None:
    """Back to the seed data's rule (or the plain name for ingredients created from recipes)."""
    ingredient.match = seed_rule(ingredient) or ""
    ingredient.match_edited = False
    ingredient.save(update_fields=["match", "match_edited"])


def add_alias(ingredient: Ingredient, name: str) -> str:
    """Add an alternative name. Returns an error message, or "" when it was added."""
    name = " ".join((name or "").split()).lower()
    if not name:
        return "Skriv ett namn."
    taken, _ = resolve(name)
    if taken:
        return f"”{name}” används redan av {taken.name}." if taken != ingredient else f"”{name}” finns redan."
    IngredientAlias.objects.create(ingredient=ingredient, name=name[:80])
    return ""


def set_shopping(ingredient: Ingredient, category: Category, staple: bool, shop: bool) -> None:
    """How the ingredient shows up in the shopping list.

    The section also decides where a rule without @ looks for products. A staple (salt, oil)
    is listed apart under "check at home"; one not in the shopping list (water) isn't listed at all.
    """
    ingredient.category = category
    ingredient.is_staple = staple
    ingredient.in_shopping_list = shop
    ingredient.save(update_fields=["category", "is_staple", "in_shopping_list"])


def named(name: str) -> Ingredient | None:
    """The ingredient whose own name (not an alias) is `name`."""
    key = " ".join((name or "").split()).lower()
    return Ingredient.objects.annotate(lname=Lower("name")).filter(lname=key).first()


@transaction.atomic
def merge(source: Ingredient, target: Ingredient) -> None:
    """Make `source` part of `target`: recipes use `target`, and the name becomes an alias.

    Recipe lines keep their amounts and notes. `target` keeps its rule and chosen product.
    """
    if source.pk == target.pk:
        raise ValueError("cannot merge an ingredient into itself")
    RecipeIngredient.objects.filter(ingredient=source).update(ingredient=target)
    # Shopping list changes ("already at home") follow, unless the week already has one for target.
    taken = ShoppingItemState.objects.filter(ingredient=target).values("week")
    ShoppingItemState.objects.filter(ingredient=source).exclude(week__in=taken).update(ingredient=target)
    source.aliases.update(ingredient=target)
    name = source.name.lower()
    source.delete()  # cascades the shopping states left behind
    IngredientAlias.objects.create(ingredient=target, name=name)


def delete(ingredient: Ingredient) -> str:
    """Delete an ingredient no recipe uses. Returns an error message, or "" when deleted."""
    if ingredient.uses.exists():
        return f"{ingredient.name} används i recept – slå ihop den med en annan ingrediens i stället."
    ingredient.delete()
    return ""
