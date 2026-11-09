"""Fill the database with seed data. Safe to run several times."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core import seed_data
from core.models import Category, Ingredient, IngredientAlias, Recipe
from core.services.recipes import find_ingredient, set_ingredients_from_text


class Command(BaseCommand):
    help = "Lägger in avdelningar, ingredienser och veganska exempelrecept (hoppar över det som finns)."

    def add_arguments(self, parser):
        parser.add_argument("--no-recipes", action="store_true", help="Lägg bara in ingredienser.")

    def handle(self, *args, **opts):
        new_ing, new_rec = self._seed(opts)
        self.stdout.write(self.style.SUCCESS(f"Klart: {new_ing} nya ingredienser, {new_rec} nya recept."))

    @transaction.atomic
    def _seed(self, opts) -> tuple[int, int]:
        cats = {}
        for name, icon, order, store_categories in seed_data.CATEGORIES:
            cats[name], _ = Category.objects.update_or_create(
                name=name, defaults={"icon": icon, "sort_order": order, "store_categories": store_categories}
            )

        new_ing = 0
        for d in seed_data.INGREDIENTS:
            existing = find_ingredient(d["name"])
            if existing:
                # The product matching follows the seed data (it isn't edited in the app).
                if existing.match != d["match"]:
                    existing.match = d["match"]
                    existing.save(update_fields=["match"])
                continue
            amount = unit = None
            if d["pkg"]:
                a, unit = d["pkg"].split()
                amount = Decimal(a)
            ing = Ingredient.objects.create(
                name=d["name"],
                category=cats[d["category"]],
                is_staple=d["staple"],
                in_shopping_list=d["shop"],
                grams_per_piece=d["gpp"],
                grams_per_dl=d["gpdl"],
                package_amount=amount,
                package_unit=unit or "",
                match=d["match"],
            )
            for alias in d["aliases"]:
                alias, unit = alias if isinstance(alias, tuple) else (alias, "")
                if not find_ingredient(alias):
                    IngredientAlias.objects.create(ingredient=ing, name=alias, implied_unit=unit)
            new_ing += 1

        new_rec = 0
        if not opts["no_recipes"]:
            for r in seed_data.RECIPES:
                if Recipe.objects.filter(name=r["name"]).exists():
                    continue
                recipe = Recipe.objects.create(
                    name=r["name"],
                    servings=r["servings"],
                    minutes=r["minutes"],
                    instructions=r["instructions"],
                    description=r["description"],
                )
                created = set_ingredients_from_text(recipe, r["ingredients"])
                if created:
                    self.stderr.write(f"Varning: {r['name']} skapade nya ingredienser: {[i.name for i in created]}")
                new_rec += 1

        return new_ing, new_rec
