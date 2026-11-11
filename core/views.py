"""Views. Thin: business logic lives in core.services and core.domain."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.domain.aggregate import Line, aggregate
from core.domain.parse import parse_line
from core.forms import RecipeForm
from core.models import (
    AppSettings,
    Category,
    ExtraItem,
    Ingredient,
    IngredientAlias,
    PlannedMeal,
    Product,
    Recipe,
    Retailer,
    ShoppingItemState,
    week_start,
)
from core.services import catalog, images, importer, index, ingredients, scheduler, shopping
from core.services.catalog import CategoryNode
from core.services.recipes import resolve, search_recipes, set_ingredients_from_text
from core.services.shopping import WEEKDAYS, WEEKDAYS_SHORT
from core.stores import axfood

MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _target(request: HttpRequest) -> str:
    return request.headers.get("HX-Target", "")


def _today() -> dt.date:
    return timezone.localdate()


def _parse_week(value: str | None) -> dt.date:
    try:
        day = dt.date.fromisoformat(value) if value else _today()
    except ValueError:
        day = _today()
    return week_start(day)


def _short_date(day: dt.date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def _day_label(day: dt.date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {_short_date(day)}"


def _week_ctx(start: dt.date) -> dict:
    end = start + dt.timedelta(days=6)
    return {
        "week": start,
        "week_no": start.isocalendar().week,
        "range": f"{_short_date(start)} – {_short_date(end)}",
        "prev": (start - dt.timedelta(days=7)).isoformat(),
        "next": (start + dt.timedelta(days=7)).isoformat(),
        "is_current": start == week_start(_today()),
    }


def home(request: HttpRequest) -> HttpResponse:
    return redirect("planner_current")


# ==================================================================== recipes


def recipe_list(request: HttpRequest) -> HttpResponse:
    q = request.GET.get("q", "").strip()
    ctx = {"recipes": search_recipes(q), "q": q}
    if _is_htmx(request) and _target(request) == "recipe-grid":
        return render(request, "core/partials/recipe_grid.html", ctx)
    return render(request, "core/recipe_list.html", ctx)


def recipe_detail(request: HttpRequest, pk: int) -> HttpResponse:
    recipe = get_object_or_404(Recipe, pk=pk)
    try:
        servings = max(1, min(int(request.GET.get("portioner", recipe.servings)), 99))
    except ValueError:
        servings = recipe.servings
    settings = AppSettings.load()
    lines, cost = shopping.recipe_lines(recipe, Decimal(servings) / Decimal(recipe.servings), settings.retailer)
    today = _today()
    week = week_start(today)
    ctx = {
        "recipe": recipe,
        "servings": servings,
        "lines": lines,
        "cost": cost,
        "retailer": settings.retailer,
        "retailer_label": settings.get_retailer_display(),
        "plan_days": [
            (
                d.isoformat(),
                ("Idag" if d == today else f"{WEEKDAYS_SHORT[d.weekday()]} {_short_date(d)}")
                + (" (nästa v.)" if d >= week + dt.timedelta(days=7) else ""),
            )
            for d in (week + dt.timedelta(days=i) for i in range(14))
            if d >= today
        ],
        "planned": PlannedMeal.objects.filter(recipe=recipe, date__gte=today).order_by("date")[:5],
        "steps": [re.sub(r"^\s*\d+[.)]\s*", "", s) for s in recipe.instructions.splitlines() if s.strip()],
    }
    if _is_htmx(request) and _target(request) == "recipe-ingredients":
        return render(request, "core/partials/recipe_ingredients.html", ctx)
    return render(request, "core/recipe_detail.html", ctx)


def _save_recipe(request: HttpRequest, form: RecipeForm) -> Recipe:
    with transaction.atomic():
        recipe = form.save(commit=False)
        upload = request.FILES.get("image")
        if form.cleaned_data.get("remove_image"):
            recipe.image = ""
        elif upload:
            f = images.normalized(upload.read())
            if f:
                recipe.image.save(f.name, f, save=False)
            else:
                recipe.image = form.initial.get("image") or ""
        elif form.cleaned_data.get("image_url") and not recipe.image:
            data = importer.download_image(form.cleaned_data["image_url"])
            f = images.normalized(data) if data else None
            if f:
                recipe.image.save(f.name, f, save=False)
        recipe.save()
        created = set_ingredients_from_text(recipe, form.cleaned_data.get("ingredient_text", ""))
    if created:
        messages.info(
            request, f"Nya ingredienser: {', '.join(i.name for i in created)}. Varor hittas automatiskt i sortimentet."
        )
    return recipe


def recipe_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = RecipeForm(request.POST, request.FILES)
        if form.is_valid():
            recipe = _save_recipe(request, form)
            messages.success(request, f"”{recipe.name}” sparades.")
            return redirect("recipe_detail", pk=recipe.pk)
    else:
        form = RecipeForm(initial={"servings": 4})
    return render(request, "core/recipe_form.html", {"form": form})


def recipe_import(request: HttpRequest) -> HttpResponse:
    url = request.POST.get("url", "").strip() if request.method == "POST" else ""
    if not url:
        return render(request, "core/recipe_import.html")
    try:
        data = importer.fetch(url)
    except importer.ImportError_ as e:
        return render(request, "core/recipe_import.html", {"error": str(e), "url": url})
    form = RecipeForm(
        initial={
            "name": data.name,
            "description": data.description,
            "servings": data.servings,
            "minutes": data.minutes,
            "instructions": data.instructions,
            "ingredient_text": "\n".join(data.ingredients),
            "image_url": data.image_url,
            "source_url": data.source_url,
        }
    )
    messages.info(request, "Receptet är importerat men inte sparat. Kontrollera ingredienserna och tryck Spara.")
    return render(request, "core/recipe_form.html", {"form": form, "image_preview": data.image_url})


def recipe_edit(request: HttpRequest, pk: int) -> HttpResponse:
    recipe = get_object_or_404(Recipe, pk=pk)
    if request.method == "POST":
        form = RecipeForm(request.POST, request.FILES, instance=recipe)
        if form.is_valid():
            _save_recipe(request, form)
            messages.success(request, "Ändringarna sparades.")
            return redirect("recipe_detail", pk=recipe.pk)
    else:
        form = RecipeForm(instance=recipe)
    return render(request, "core/recipe_form.html", {"form": form, "recipe": recipe})


@require_POST
def recipe_delete(request: HttpRequest, pk: int) -> HttpResponse:
    recipe = get_object_or_404(Recipe, pk=pk)
    name = recipe.name
    recipe.delete()
    messages.success(request, f"”{name}” togs bort.")
    return redirect("recipe_list")


@require_POST
def ingredient_preview(request: HttpRequest) -> HttpResponse:
    """Show how the ingredient lines are parsed, and which product they become, while typing."""
    retailer = AppSettings.load().retailer
    rows = []
    for raw in request.POST.get("ingredient_text", "").splitlines()[:60]:
        p = parse_line(raw)
        if p is None:
            continue
        match, implied = resolve(p.name)
        unit = implied if implied and p.quantity is not None and p.unit in ("", "st") else p.unit
        best = None
        if match and match.in_shopping_list and not match.is_staple:
            item = aggregate([Line(match.pk, p.quantity, unit)], {match.pk: match.facts()}).get(match.pk)
            best, _ = catalog.choose(match, item, retailer)
        rows.append({"parsed": p, "match": match, "unit": unit, "offer": best})
    return render(request, "core/partials/ingredient_preview.html", {"rows": rows})


@require_POST
def recipe_plan(request: HttpRequest, pk: int) -> HttpResponse:
    recipe = get_object_or_404(Recipe, pk=pk)
    try:
        day = dt.date.fromisoformat(request.POST["date"])
        servings = max(1, min(int(request.POST.get("servings") or recipe.servings), 99))
    except (KeyError, ValueError):
        messages.error(request, "Välj en dag.")
        return redirect("recipe_detail", pk=pk)
    _add_meal(day, recipe, servings)
    messages.success(request, f"”{recipe.name}” lades till på {_day_label(day).lower()}.")
    return redirect(reverse("recipe_detail", args=[pk]) + f"?portioner={servings}")


# ===================================================================== week


def _add_meal(day: dt.date, recipe: Recipe, servings: int) -> PlannedMeal:
    pos = PlannedMeal.objects.filter(date=day).aggregate(m=Max("position"))["m"]
    return PlannedMeal.objects.create(date=day, recipe=recipe, servings=servings, position=(pos or 0) + 1)


def _day_ctx(day: dt.date) -> dict:
    return {
        "date": day,
        "label": WEEKDAYS[day.weekday()],
        "sub": _short_date(day),
        "today": day == _today(),
        "past": day < _today(),
        "meals": PlannedMeal.objects.filter(date=day).select_related("recipe"),
    }


def planner(request: HttpRequest, week: str | None = None) -> HttpResponse:
    start = _parse_week(week)
    if week and start.isoformat() != week:
        return redirect("planner", week=start.isoformat())
    days = [_day_ctx(start + dt.timedelta(days=i)) for i in range(7)]
    prev_has = PlannedMeal.objects.filter(date__gte=start - dt.timedelta(days=7), date__lt=start).exists()
    return render(
        request,
        "core/planner.html",
        {
            **_week_ctx(start),
            "days": days,
            "meal_count": sum(len(d["meals"]) for d in days),
            "list": shopping.build(start, AppSettings.load().retailer),
            "prev_has_meals": prev_has,
            "index_empty": not Product.objects.filter(vegan=True).exists(),
        },
    )


def recipe_picker(request: HttpRequest) -> HttpResponse:
    day = dt.date.fromisoformat(request.GET["date"])
    q = request.GET.get("q", "").strip()
    ctx = {
        "date": day,
        "day_label": _day_label(day),
        "recipes": search_recipes(q)[:80],
        "q": q,
        "default_servings": AppSettings.load().default_servings,
    }
    if _target(request) == "picker-results":
        return render(request, "core/partials/picker_results.html", ctx)
    return render(request, "core/partials/picker.html", ctx)


@require_POST
def meal_add(request: HttpRequest) -> HttpResponse:
    day = dt.date.fromisoformat(request.POST["date"])
    recipe = get_object_or_404(Recipe, pk=request.POST["recipe"])
    settings = AppSettings.load()
    try:
        servings = max(1, min(int(request.POST.get("servings") or settings.default_servings), 99))
    except ValueError:
        servings = settings.default_servings
    if servings != settings.default_servings:  # remember the last choice
        AppSettings.objects.filter(pk=1).update(default_servings=servings)
    _add_meal(day, recipe, servings)
    return _day_response(request, day)


def day_partial(request: HttpRequest, date: str) -> HttpResponse:
    return render(request, "core/partials/day.html", {"day": _day_ctx(dt.date.fromisoformat(date))})


def _day_response(request: HttpRequest, day: dt.date) -> HttpResponse:
    resp = render(request, "core/partials/day.html", {"day": _day_ctx(day)})
    resp["HX-Trigger"] = "plan-changed"
    return resp


@require_POST
def meal_servings(request: HttpRequest, pk: int) -> HttpResponse:
    meal = get_object_or_404(PlannedMeal, pk=pk)
    meal.servings = max(1, min(meal.servings + int(request.POST.get("delta", 0)), 99))
    meal.save(update_fields=["servings"])
    return _day_response(request, meal.date)


@require_POST
def meal_delete(request: HttpRequest, pk: int) -> HttpResponse:
    meal = get_object_or_404(PlannedMeal, pk=pk)
    day = meal.date
    meal.delete()
    return _day_response(request, day)


@require_POST
def meal_move(request: HttpRequest) -> HttpResponse:
    """Drag and drop: move a meal to a day and set the order for that day."""
    meal = get_object_or_404(PlannedMeal, pk=request.POST["id"])
    day = dt.date.fromisoformat(request.POST["date"])
    order = [int(x) for x in request.POST.get("order", "").split(",") if x.strip().isdigit()]
    with transaction.atomic():
        meal.date = day
        meal.save(update_fields=["date"])
        for pos, mid in enumerate(order):
            PlannedMeal.objects.filter(pk=mid, date=day).update(position=pos)
    resp = HttpResponse(status=204)
    resp["HX-Trigger"] = "plan-changed"
    return resp


@require_POST
def week_copy_previous(request: HttpRequest, week: str) -> HttpResponse:
    start = _parse_week(week)
    meals = list(PlannedMeal.objects.filter(date__gte=start - dt.timedelta(days=7), date__lt=start))
    PlannedMeal.objects.bulk_create(
        PlannedMeal(
            date=m.date + dt.timedelta(days=7), recipe_id=m.recipe_id, servings=m.servings, position=m.position + 100
        )
        for m in meals
    )
    messages.success(
        request, f"Kopierade {len(meals)} {'måltid' if len(meals) == 1 else 'måltider'} från förra veckan."
    )
    return redirect("planner", week=start.isoformat())


@require_POST
def week_clear(request: HttpRequest, week: str) -> HttpResponse:
    start = _parse_week(week)
    n, _ = PlannedMeal.objects.filter(date__gte=start, date__lt=start + dt.timedelta(days=7)).delete()
    messages.success(request, f"Tömde veckan ({n} {'måltid' if n == 1 else 'måltider'}).")
    return redirect("planner", week=start.isoformat())


def week_summary(request: HttpRequest, week: str) -> HttpResponse:
    start = _parse_week(week)
    sl = shopping.build(start, AppSettings.load().retailer)
    return render(request, "core/partials/week_summary.html", {"list": sl, "week": start})


# ====================================================================== shopping


def _shopping_ctx(start: dt.date) -> dict:
    settings = AppSettings.load()
    return {
        **_week_ctx(start),
        "list": shopping.build(start, settings.retailer),
        "retailer": settings.retailer,
        "retailer_label": settings.get_retailer_display(),
        "retailers": Retailer.choices,
        "index_empty": not Product.objects.filter(vegan=True).exists(),
    }


def shopping_list(request: HttpRequest, week: str | None = None) -> HttpResponse:
    start = _parse_week(week)
    if week and start.isoformat() != week:
        return redirect("shopping", week=start.isoformat())
    return render(request, "core/shopping.html", _shopping_ctx(start))


def _refresh() -> HttpResponse:
    resp = HttpResponse("")
    resp["HX-Refresh"] = "true"
    return resp


@require_POST
def shopping_item(request: HttpRequest, week: str, ingredient_id: int) -> HttpResponse:
    start = _parse_week(week)
    ing = get_object_or_404(Ingredient, pk=ingredient_id)
    state, _ = ShoppingItemState.objects.get_or_create(week=start, ingredient=ing)
    action = request.POST.get("action")
    if action in ("remove", "restore"):  # "already at home" / undo
        state.removed = action == "remove"
        state.save()
    return _refresh()


def shopping_choose(request: HttpRequest, week: str, ingredient_id: int) -> HttpResponse:
    """Dialog: choose a product for an ingredient. Cheapest for the amount first."""
    start = _parse_week(week)
    ing = get_object_or_404(Ingredient.objects.select_related("category"), pk=ingredient_id)
    retailer = AppSettings.load().retailer
    if request.method == "POST":
        code = request.POST.get("code", "")
        ing.preferred_code = code if Product.objects.filter(code=code, vegan=True).exists() else ""
        ing.save(update_fields=["preferred_code"])
        return _refresh()

    sl = shopping.build(start, retailer)
    row = next((r for r in sl.all_rows if r.ingredient_id == ing.pk), None)
    item = _item_for(start, ing)
    q = request.GET.get("q", "").strip()
    products = catalog.search(q, retailer) if q else None
    offers = catalog.offers(ing, item, retailer, products)
    ctx = {
        "ingredient": ing,
        "row": row,
        "offers": offers,
        "q": q,
        "week": start,
        "retailer_label": Retailer(retailer).label,
    }
    if _target(request) == "choose-results":
        return render(request, "core/partials/choose_results.html", ctx)
    return render(request, "core/partials/choose.html", ctx)


def _item_for(week: dt.date, ing: Ingredient):
    lines = []
    for meal in shopping.meals_for_week(week):
        for ri in meal.recipe.ingredients.all():
            if ri.ingredient_id == ing.pk:
                q = (
                    ri.quantity * Decimal(meal.servings) / Decimal(meal.recipe.servings)
                    if ri.quantity is not None
                    else None
                )
                lines.append(Line(ing.pk, q, ri.unit, meal.id))
    return aggregate(lines, {ing.pk: ing.facts()}).get(ing.pk)


def extra_search(request: HttpRequest, week: str) -> HttpResponse:
    start = _parse_week(week)
    retailer = AppSettings.load().retailer
    q = request.GET.get("q", "").strip()
    results = catalog.search(q, retailer, limit=30) if q else []
    return render(
        request,
        "core/partials/extra_results.html",
        {
            "results": [(p, catalog.price_at(p, retailer)) for p in results],
            "q": q,
            "week": start,
        },
    )


@require_POST
def extra_add(request: HttpRequest, week: str) -> HttpResponse:
    start = _parse_week(week)
    product = get_object_or_404(Product, code=request.POST.get("code", ""), vegan=True)
    item, created = ExtraItem.objects.get_or_create(week=start, product=product)
    if not created:
        item.count += 1
        item.save(update_fields=["count"])
    return redirect("shopping", week=start.isoformat())


@require_POST
def extra_item(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(ExtraItem, pk=pk)
    action = request.POST.get("action")
    if action == "delete" or (action == "minus" and item.count <= 1):
        item.delete()
    elif action in ("plus", "minus"):
        item.count = min(item.count + 1, 99) if action == "plus" else item.count - 1
        item.save()
    return _refresh()


@require_POST
def set_retailer(request: HttpRequest) -> HttpResponse:
    value = request.POST.get("retailer")
    if value in Retailer.values:
        AppSettings.load()
        AppSettings.objects.filter(pk=1).update(retailer=value)
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") else "shopping_current")


# =================================================================== range (sortiment)


def _index_ctx() -> dict:
    settings = AppSettings.load()
    return {
        "settings": settings,
        "running": index.is_running(),
        "progress": settings.index_progress,
        "in_window": axfood.in_visit_time(),
        "next_window": timezone.localtime(axfood.next_visit_time()),
        "auto_refresh": scheduler.is_active(),  # running under `manage.py serve`
        "stats": {
            "total": Product.objects.count(),
            "vegan": Product.objects.filter(vegan=True).count(),
            "unchecked": Product.objects.filter(checked_at__isnull=True).count(),
        },
    }


def products_view(request: HttpRequest) -> HttpResponse:
    settings = AppSettings.load()
    retailer = settings.retailer
    q = request.GET.get("q", "").strip()
    category = request.GET.get("kategori", "")
    promo_only = request.GET.get("erbjudande") == "1"
    sort = request.GET.get("sortera", "")
    # Kept when moving between categories.
    filters = urlencode(
        {k: v for k, v in (("q", q), ("erbjudande", "1" if promo_only else ""), ("sortera", sort)) if v}
    )
    qs = catalog.vegan_products(retailer)
    if q:
        qs = Product.objects.filter(pk__in=[p.pk for p in catalog.search(q, retailer, limit=300)])
        qs = qs.prefetch_related("prices")
    tree = catalog.category_tree(retailer)
    current = None  # selected category (top or sub) for the heading
    if category:
        # "skafferi" = the whole top category, "skafferi/asien" = one subcategory
        qs = qs.filter(category=category) if "/" in category else qs.filter(category__startswith=category + "/")
        for top in tree:
            if top.slug == category:
                current = top
            for child in top.children:
                if child.slug == category:
                    current = CategoryNode(child.slug, f"{top.name} › {child.name}", child.count)
    products = list(catalog.filter_range(qs, retailer, promo_only, sort)[:300])
    ctx = {
        **_index_ctx(),
        "rows": [(p, catalog.price_at(p, "willys"), catalog.price_at(p, "hemkop")) for p in products],
        "q": q,
        "promo_only": promo_only,
        "sort": sort,
        "filters": filters,
        "filtered": promo_only,
        "category": category,
        "tree": tree,
        "current": current,
        "open_top": category.split("/")[0],
        "retailer": retailer,
        "shown": len(products),
        "total_vegan": sum(t.count for t in tree),
    }
    if _is_htmx(request) and _target(request) == "product-table":
        # The category links carry the filters, so the tree is updated alongside the table.
        table = render(request, "core/partials/product_table.html", ctx).content
        tree = render(request, "core/partials/products_tree.html", {**ctx, "oob": True}).content
        return HttpResponse(table + tree)
    return render(request, "core/products.html", ctx)


def index_status(request: HttpRequest) -> HttpResponse:
    return render(request, "core/partials/index_status.html", _index_ctx())


@require_POST
def index_start(request: HttpRequest) -> HttpResponse:
    index.start_background()
    return render(request, "core/partials/index_status.html", _index_ctx())


# =================================================================== ingredients


def ingredient_list(request: HttpRequest) -> HttpResponse:
    q = request.GET.get("q", "").strip()
    qs = Ingredient.objects.select_related("category").annotate(
        n_aliases=Count("aliases", distinct=True), n_recipes=Count("uses__recipe", distinct=True)
    )
    if q:
        hits = Ingredient.objects.filter(Q(name__icontains=q) | Q(aliases__name__icontains=q)).values("pk")
        qs = qs.filter(pk__in=hits)
    ctx = {"ingredients": qs.order_by("category__sort_order", "category__name", "name"), "q": q}
    if _is_htmx(request) and _target(request) == "ingredient-table":
        return render(request, "core/partials/ingredient_table.html", ctx)
    return render(request, "core/ingredient_list.html", ctx)


def _ingredient(pk: int) -> Ingredient:
    return get_object_or_404(Ingredient.objects.select_related("category"), pk=pk)


def _alias_ctx(ing: Ingredient, error: str = "", merge_from: Ingredient | None = None) -> dict:
    return {"ingredient": ing, "aliases": ing.aliases.order_by("name"), "alias_error": error, "merge_from": merge_from}


def ingredient_detail(request: HttpRequest, pk: int) -> HttpResponse:
    ing = _ingredient(pk)
    if request.method == "POST":
        ingredients.set_match(ing, request.POST.get("match", ""))
        messages.success(request, f"Varumatchningen för {ing.name.lower()} sparades.")
        return redirect("ingredient_detail", pk=ing.pk)
    retailer = AppSettings.load().retailer
    ctx = {
        **_alias_ctx(ing),
        "preview": ingredients.preview(ing, ing.match, retailer),
        "seed_rule": ingredients.seed_rule(ing),
        "store_categories": (ing.category.store_categories or "").split(),
        "recipes": Recipe.objects.filter(ingredients__ingredient=ing).distinct().order_by("name"),
        "retailer_label": Retailer(retailer).label,
        "others": Ingredient.objects.exclude(pk=ing.pk).order_by("name").values_list("name", flat=True),
        "categories": Category.objects.all(),
    }
    return render(request, "core/ingredient_detail.html", ctx)


def match_preview(request: HttpRequest, pk: int) -> HttpResponse:
    ing = _ingredient(pk)
    retailer = AppSettings.load().retailer
    ctx = {
        "ingredient": ing,
        "preview": ingredients.preview(ing, request.GET.get("match", ""), retailer),
        "retailer_label": Retailer(retailer).label,
    }
    return render(request, "core/partials/match_preview.html", ctx)


@require_POST
def ingredient_reset(request: HttpRequest, pk: int) -> HttpResponse:
    ing = _ingredient(pk)
    ingredients.reset_match(ing)
    messages.success(request, f"Varumatchningen för {ing.name.lower()} återställdes.")
    return redirect("ingredient_detail", pk=ing.pk)


@require_POST
def alias_add(request: HttpRequest, pk: int) -> HttpResponse:
    ing = _ingredient(pk)
    name = request.POST.get("name", "")
    error = ingredients.add_alias(ing, name)
    if _is_htmx(request):
        # The name is another ingredient of its own (e.g. created from a recipe): offer to merge it.
        other = ingredients.named(name) if error else None
        merge_from = other if other and other != ing else None
        return render(request, "core/partials/alias_list.html", _alias_ctx(ing, error, merge_from))
    if error:
        messages.error(request, error)
    return redirect("ingredient_detail", pk=ing.pk)


@require_POST
def alias_delete(request: HttpRequest, pk: int) -> HttpResponse:
    alias = get_object_or_404(IngredientAlias.objects.select_related("ingredient__category"), pk=pk)
    ing = alias.ingredient
    alias.delete()
    if _is_htmx(request):
        return render(request, "core/partials/alias_list.html", _alias_ctx(ing))
    return redirect("ingredient_detail", pk=ing.pk)


@require_POST
def ingredient_section(request: HttpRequest, pk: int) -> HttpResponse:
    """How the ingredient shows up in the shopping list: section, staple, or not at all."""
    ing = _ingredient(pk)
    category = get_object_or_404(Category, pk=request.POST.get("category") or 0)
    ingredients.set_shopping(
        ing, category, staple=bool(request.POST.get("is_staple")), shop=bool(request.POST.get("in_shopping_list"))
    )
    messages.success(request, f"Inköpslistan för {ing.name.lower()} sparades.")
    return redirect("ingredient_detail", pk=ing.pk)


@require_POST
def ingredient_merge(request: HttpRequest, pk: int) -> HttpResponse:
    """Merge this ingredient into the one named in `into`; its name becomes an alias there."""
    ing = _ingredient(pk)
    into = request.POST.get("into", "")
    target = ingredients.named(into)
    if not target or target == ing:
        messages.error(request, f"Hittade ingen annan ingrediens som heter ”{into.strip()}”.")
        return redirect("ingredient_detail", pk=ing.pk)
    name = ing.name
    ingredients.merge(ing, target)
    messages.success(request, f"{name} slogs ihop med {target.name} och är nu ett alias.")
    return redirect("ingredient_detail", pk=target.pk)


@require_POST
def ingredient_delete(request: HttpRequest, pk: int) -> HttpResponse:
    ing = _ingredient(pk)
    name = ing.name
    error = ingredients.delete(ing)
    if error:
        messages.error(request, error)
        return redirect("ingredient_detail", pk=pk)
    messages.success(request, f"{name} togs bort.")
    return redirect("ingredient_list")
