"""Recipes: store ingredient text, find ingredients, plan."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower

from core.domain.parse import normalize_name, parse_line
from core.models import (
    Category,
    Ingredient,
    IngredientAlias,
    Product,
    Recipe,
    RecipeIngredient,
)
from core.services.index import normalize

FALLBACK_CATEGORY = "Övrigt"


def resolve(name: str) -> tuple[Ingredient | None, str]:
    """Exact (case-insensitive) match on name or alias. Never 'similar'.

    Returns (ingredient, implied unit from the alias or "").
    """
    key = normalize_name(name)
    ing = Ingredient.objects.annotate(lname=Lower("name")).filter(lname=key).first()
    if ing:
        return ing, ""
    alias = (
        IngredientAlias.objects.annotate(lname=Lower("name"))
        .filter(lname=key)
        .select_related("ingredient")
        .first()
    )
    return (alias.ingredient, alias.implied_unit) if alias else (None, "")


def find_ingredient(name: str) -> Ingredient | None:
    return resolve(name)[0]


def get_or_create_ingredient(name: str) -> tuple[Ingredient, bool]:
    ing, _ = resolve(name)
    if ing:
        return ing, False
    clean = " ".join(name.split())
    return Ingredient.objects.create(name=clean[:1].upper() + clean[1:], category=guess_category(clean)), True


def guess_category(name: str) -> Category:
    """Section for a new ingredient: where the index's products with the same name are.

    The product matching is then the ingredient's name within that section's store categories.
    """
    words = normalize(name).split()
    product_cats: dict[str, int] = {}
    if words:
        qs = Product.objects.all()
        for w in words:
            qs = qs.filter(search_text__regex=r"(^| )" + w)
        for cat in qs.values_list("category", flat=True)[:200]:
            product_cats[cat] = product_cats.get(cat, 0) + 1
    best, best_score = None, 0
    for c in Category.objects.exclude(store_categories=""):
        prefixes = c.store_categories.split()
        score = sum(n for pc, n in product_cats.items() if any(pc.startswith(p) for p in prefixes))
        if score > best_score:
            best, best_score = c, score
    if best:
        return best
    return Category.objects.get_or_create(name=FALLBACK_CATEGORY, defaults={"sort_order": 999})[0]


@transaction.atomic
def set_ingredients_from_text(recipe: Recipe, text: str) -> list[Ingredient]:
    """Replace the recipe's ingredients with the parsed lines. Returns newly created ingredients."""
    created: list[Ingredient] = []
    rows: list[RecipeIngredient] = []
    for pos, raw in enumerate(text.splitlines()):
        parsed = parse_line(raw)
        if parsed is None:
            continue
        _, implied_unit = resolve(parsed.name)
        ing, was_created = get_or_create_ingredient(parsed.name)
        if was_created:
            created.append(ing)
        unit = parsed.unit
        if implied_unit and parsed.quantity is not None and unit in ("", "st"):
            unit = implied_unit
        rows.append(
            RecipeIngredient(
                recipe=recipe,
                ingredient=ing,
                quantity=parsed.quantity,
                unit=unit,
                note=parsed.note[:120],
                position=pos,
            )
        )
    recipe.ingredients.all().delete()
    RecipeIngredient.objects.bulk_create(rows)
    return created


def search_recipes(query: str = ""):
    qs = Recipe.objects.all()
    if query:
        qs = qs.filter(
            Q(name__icontains=query) | Q(ingredients__ingredient__name__icontains=query)
        ).distinct()
    return qs
