from django.contrib import admin

from core import models as m


class AliasInline(admin.TabularInline):
    model = m.IngredientAlias
    extra = 1


@admin.register(m.Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_staple", "package_amount", "package_unit", "match", "preferred_code"]
    list_filter = ["category", "is_staple"]
    search_fields = ["name", "aliases__name"]
    inlines = [AliasInline]


class RecipeIngredientInline(admin.TabularInline):
    model = m.RecipeIngredient
    extra = 0
    autocomplete_fields = ["ingredient"]


@admin.register(m.Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ["name", "servings", "minutes"]
    search_fields = ["name"]
    inlines = [RecipeIngredientInline]


class PriceInline(admin.TabularInline):
    model = m.Price
    extra = 0


@admin.register(m.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "brand", "size_text", "category", "vegan", "vegan_reason", "checked_at"]
    list_filter = ["vegan", "category"]
    search_fields = ["name", "brand", "ean", "code"]
    inlines = [PriceInline]


for model in (m.Category, m.PlannedMeal, m.ShoppingItemState, m.ExtraItem, m.AppSettings):
    admin.site.register(model)
