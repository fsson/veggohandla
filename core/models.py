"""Data model.

Three levels are kept apart (see docs/ARCHITECTURE.md):
  RecipeIngredient  -> a line in a recipe ("500 g mjölig potatis")
  Ingredient        -> what it is ("Mjölig potatis"); matches a group of products in the index
  Product           -> a real product in the chains' range ("Potatis Mjölig 2kg Garant")
Recipes always point at Ingredient. Which product gets bought is only decided in the shopping list.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import models
from django.db.models.functions import Lower

from core.domain.units import MASS, PIECE, IngredientFacts, to_base

Q = dict(max_digits=12, decimal_places=3, null=True, blank=True)
MONEY = dict(max_digits=9, decimal_places=2, null=True, blank=True)


class Category(models.Model):
    """A section of the shopping list. The order controls the grouping."""

    name = models.CharField("namn", max_length=60, unique=True)
    icon = models.CharField("ikon", max_length=8, blank=True)
    sort_order = models.PositiveIntegerField("ordning", default=100)
    # Store categories (Willys paths, space-separated prefixes) where ingredients in
    # this section look for products unless they specify their own.
    store_categories = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "kategori"
        verbose_name_plural = "kategorier"

    def __str__(self) -> str:
        return self.name


class Ingredient(models.Model):
    PACKAGE_UNITS = [("g", "g"), ("kg", "kg"), ("ml", "ml"), ("dl", "dl"), ("l", "l"), ("st", "st")]

    name = models.CharField("namn", max_length=80)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name="kategori")
    is_staple = models.BooleanField("basvara", default=False)  # salt, oil … shown separately
    in_shopping_list = models.BooleanField("visa i inköpslistan", default=True)  # off for water
    grams_per_piece = models.DecimalField("gram per st", **Q)
    grams_per_dl = models.DecimalField("gram per dl", **Q)
    package_amount = models.DecimalField("förpackningsstorlek", **Q)
    package_unit = models.CharField("förp.enhet", max_length=4, choices=PACKAGE_UNITS, blank=True)
    # Which products in the index count as "this ingredient", see services/catalog.py.
    match = models.CharField("varumatchning", max_length=300, blank=True)
    # True when the rule was changed on the ingredient page: `seed` then leaves it alone.
    match_edited = models.BooleanField(default=False)
    # Chosen product (article code). Empty = the cheapest for the amount is picked automatically.
    preferred_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="ingredient_name_ci_unique")]
        verbose_name = "ingrediens"
        verbose_name_plural = "ingredienser"

    def __str__(self) -> str:
        return self.name

    def facts(self, product: Product | None = None) -> IngredientFacts:
        """Conversion facts.

        "förp" in a recipe always means the ingredient's standard package. A chosen
        product only affects how many packages are bought (purchase_*).
        """
        pkg_amount = pkg_dim = None
        if self.package_amount and self.package_unit:
            pkg_amount, pkg_dim = to_base(self.package_amount, self.package_unit)
        buy_amount = buy_dim = None
        if product and product.size_amount and product.size_unit and not product.price_per_kg:
            buy_amount, buy_dim = to_base(product.size_amount, product.size_unit)
            gpp = self.grams_per_piece
            if buy_dim == MASS and gpp and gpp * Decimal("0.6") <= buy_amount <= gpp * Decimal("1.5"):
                # A product weighing about one piece IS one piece ("Avokado 147 g" = 1 avocado).
                buy_amount, buy_dim = Decimal(1), PIECE
        return IngredientFacts(
            grams_per_piece=self.grams_per_piece,
            grams_per_dl=self.grams_per_dl,
            package_amount=pkg_amount,
            package_dimension=pkg_dim,
            purchase_amount=buy_amount,
            purchase_dimension=buy_dim,
        )


class IngredientAlias(models.Model):
    """Alternative name for exact matching when entering text ("gula lökar" -> Gul lök)."""

    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name="aliases")
    name = models.CharField(max_length=80)
    # "2 vitlöksklyftor" should mean 2 cloves, not 2 pieces of garlic.
    implied_unit = models.CharField(max_length=10, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("name"), name="alias_name_ci_unique")]

    def __str__(self) -> str:
        return self.name


class Recipe(models.Model):
    name = models.CharField("namn", max_length=120)
    description = models.TextField("beskrivning", blank=True)
    image = models.ImageField("bild", upload_to="recept/", blank=True)
    servings = models.PositiveSmallIntegerField("portioner", default=4)
    minutes = models.PositiveSmallIntegerField("tid (min)", null=True, blank=True)
    instructions = models.TextField("instruktioner", blank=True)
    source_url = models.URLField("källa", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def ingredient_text(self) -> str:
        """The ingredients as editable text, one line per ingredient."""
        return "\n".join(ri.as_text() for ri in self.ingredients.select_related("ingredient"))


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="uses")
    quantity = models.DecimalField(**Q)  # None = "to taste"
    unit = models.CharField(max_length=10, blank=True)
    note = models.CharField(max_length=120, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def as_text(self, factor: Decimal = Decimal(1)) -> str:
        from core.domain.units import UNITS, format_number

        parts = []
        if self.quantity is not None:
            qty = self.quantity * factor
            parts.append(format_number(qty))
            if self.unit and self.unit != "st":
                u = UNITS.get(self.unit)
                parts.append(u.plural if u and u.plural and qty > 1 else self.unit)
        parts.append(self.ingredient.name.lower() if parts else self.ingredient.name)
        text = " ".join(parts)
        return f"{text}, {self.note}" if self.note else text


class PlannedMeal(models.Model):
    """A meal on a day. A week is just a date range – no table of its own."""

    date = models.DateField(db_index=True)
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="planned")
    servings = models.PositiveSmallIntegerField(default=4)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["date", "position", "id"]


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


class ShoppingItemState(models.Model):
    """The user's change to a computed shopping row. The row itself is never stored."""

    week = models.DateField()  # Monday
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    removed = models.BooleanField(default=False)  # "already at home"

    class Meta:
        constraints = [models.UniqueConstraint("week", "ingredient", name="state_week_ingredient")]


# ------------------------------------------------------------------- stores


class Retailer(models.TextChoices):
    WILLYS = "willys", "Willys"
    HEMKOP = "hemkop", "Hemköp"


class Product(models.Model):
    """A product in the index. Willys and Hemköp share article codes (both owned by Axfood)."""

    code = models.CharField(max_length=40, unique=True)
    ean = models.CharField(max_length=14, blank=True)
    name = models.CharField(max_length=160)
    brand = models.CharField(max_length=80, blank=True)
    size_text = models.CharField(max_length=40, blank=True)
    size_amount = models.DecimalField(**Q)
    size_unit = models.CharField(max_length=4, blank=True)  # g, ml or st
    price_per_kg = models.BooleanField(default=False)  # loose weight: the price is per kg
    image_url = models.URLField(max_length=400, blank=True)
    category = models.CharField(max_length=120, db_index=True)  # "skafferi/asien"
    category_name = models.CharField(max_length=120, blank=True)  # "Skafferi › Asien"
    search_text = models.CharField(max_length=300, blank=True)  # lowercase, for matching
    ingredients = models.TextField(blank=True)
    diet = models.CharField(max_length=80, blank=True)
    vegan = models.BooleanField(null=True)  # None = not checked/unknown -> never shown
    vegan_reason = models.CharField(max_length=120, blank=True)  # reason code, see domain/vegan.py
    checked_at = models.DateTimeField(null=True, blank=True)  # details fetched
    seen_at = models.DateTimeField(null=True, blank=True)  # last seen in Willys' range

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def title(self) -> str:
        return " ".join(x for x in (self.name, self.size_text) if x)

    def url(self, retailer: str = "willys") -> str:
        from core.stores import axfood

        return axfood.product_url(retailer, self.code, self.name)


class Price(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="prices")
    retailer = models.CharField(max_length=20, choices=Retailer.choices)
    price = models.DecimalField(**MONEY)
    compare_price = models.CharField(max_length=40, blank=True)
    promo_price = models.DecimalField(**MONEY)
    promo_min = models.PositiveSmallIntegerField(default=1)  # "2 för 46" -> 2
    promo_text = models.CharField(max_length=80, blank=True)
    promo_until = models.DateField(null=True, blank=True)
    seen_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint("product", "retailer", name="price_product_retailer")]

    def promo_active(self, today: dt.date | None = None) -> bool:
        today = today or dt.date.today()
        return bool(self.promo_price and (self.promo_until is None or self.promo_until >= today))

    def unit_price(self, quantity: int = 1) -> Decimal | None:
        """Price per package (or per kg for loose weight). A promotion applies from promo_min units."""
        if self.promo_active() and quantity >= self.promo_min:
            return self.promo_price
        return self.price


class ExtraItem(models.Model):
    """A product from the index added to the week's list without being part of a recipe."""

    week = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    count = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint("week", "product", name="extra_week_product")]


class AppSettings(models.Model):
    """Singleton: chosen chain, last servings choice and the index status."""

    retailer = models.CharField(max_length=20, choices=Retailer.choices, default=Retailer.WILLYS)
    default_servings = models.PositiveSmallIntegerField(default=2)
    index_running = models.BooleanField(default=False)
    index_progress = models.CharField(max_length=400, blank=True)
    index_error = models.CharField(max_length=300, blank=True)
    index_heartbeat = models.DateTimeField(null=True, blank=True)  # last sign of life from a run
    listed_at = models.DateTimeField(null=True, blank=True)  # last complete pass over the category listings
    indexed_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def load(cls) -> AppSettings:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
