import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import (
    AppSettings,
    Category,
    ExtraItem,
    Ingredient,
    PlannedMeal,
    Price,
    Product,
    Recipe,
    ShoppingItemState,
    week_start,
)
from core.services import catalog, importer, index, shopping
from core.services.recipes import find_ingredient, get_or_create_ingredient, set_ingredients_from_text
from core.stores import axfood
from core.stores.axfood import Details, ProductData
from core.tests.conftest import add_test_recipes

WEEK = dt.date(2026, 11, 2)  # a Monday


@pytest.fixture
def seeded(db):
    call_command("seed", stdout=open("/dev/null", "w"))
    add_test_recipes()  # recipes the tests use besides the 5 seed recipes


def plan(name: str, day_offset: int, servings: int) -> PlannedMeal:
    return PlannedMeal.objects.create(
        date=WEEK + dt.timedelta(days=day_offset), recipe=Recipe.objects.get(name=name), servings=servings
    )


def rows_by_name(sl):
    return {r.name: r for r in sl.all_rows + sl.staples}


def product(code, name, category, size, willys=None, hemkop=None, vegan=True, per_kg=False, promo=None):
    """Create a product in the index with a price at one or both chains."""
    amount, unit = axfood.parse_size(size)
    if per_kg:
        amount, unit = D(1000), "g"
    p = Product.objects.create(
        code=code,
        name=name,
        category=category,
        size_text=size,
        size_amount=amount,
        size_unit=unit,
        price_per_kg=per_kg,
        search_text=index.normalize(name),
        vegan=vegan,
    )
    now = timezone.now()
    for retailer, price in (("willys", willys), ("hemkop", hemkop)):
        if price is not None:
            kw = {}
            if promo and retailer == "willys":
                kw = dict(promo_price=D(promo[0]), promo_min=promo[1], promo_text="kampanj")
            Price.objects.create(product=p, retailer=retailer, price=D(price), seen_at=now, **kw)
    return p


# ------------------------------------------------------------------- seed


def test_seed_creates_no_unknown_ingredients(seeded):
    from core import seed_data

    names = {r["name"] for r in seed_data.RECIPES}
    assert len(names) == 5 and names <= set(Recipe.objects.values_list("name", flat=True))
    # Every recipe line (seed and test recipes) matched a seeded ingredient – no new ones were created.
    assert Ingredient.objects.count() == len(seed_data.INGREDIENTS)
    assert not any("image" in r for r in seed_data.RECIPES)


def test_seed_recipes_have_no_images(db):
    call_command("seed", stdout=open("/dev/null", "w"))
    assert Recipe.objects.count() == 5 and not Recipe.objects.exclude(image="").exists()


def test_seed_is_idempotent_and_updates_match_rules(seeded):
    n = Ingredient.objects.count()
    Ingredient.objects.filter(name="Tofu").update(match="fel")
    call_command("seed", stdout=open("/dev/null", "w"))
    assert Ingredient.objects.count() == n
    assert Ingredient.objects.get(name="Tofu").match != "fel"


# ------------------------------------------------------------------- recipes


def test_find_ingredient_by_alias_case_insensitive(seeded):
    assert find_ingredient("GULA LÖKAR").name == "Gul lök"
    assert find_ingredient("gul lök ").name == "Gul lök"
    assert find_ingredient("lökringar") is None  # no 'similar' matching


def test_unknown_ingredient_gets_category_from_index(seeded):
    product("1", "Drakfrukt Klass 1", "frukt-och-gront/frukt", "300g", willys="20")
    ing, created = get_or_create_ingredient("drakfrukt")
    assert created and ing.name == "Drakfrukt" and ing.category.name == "Frukt & grönt"
    again, created = get_or_create_ingredient("Drakfrukt")
    assert not created and again.pk == ing.pk
    other, _ = get_or_create_ingredient("Något helt okänt")
    assert other.category.name == "Övrigt"


def test_set_ingredients_from_text(seeded):
    r = Recipe.objects.create(name="Test", servings=2)
    new = set_ingredients_from_text(r, "500 g mjölig potatis\n\n1 gul lök, hackad\nSalt\n2 st drakfrukt")
    assert [i.name for i in new] == ["Drakfrukt"]
    rows = list(r.ingredients.select_related("ingredient"))
    assert [(x.ingredient.name, x.quantity, x.unit, x.note) for x in rows] == [
        ("Mjölig potatis", D("500"), "g", ""),
        ("Gul lök", D("1"), "st", "hackad"),
        ("Salt", None, "", ""),
        ("Drakfrukt", D("2"), "st", ""),
    ]
    assert r.ingredient_text().splitlines()[1] == "1 gul lök, hackad"


def test_recipe_text_uses_plural_units(seeded):
    r = Recipe.objects.create(name="T", servings=2)
    set_ingredients_from_text(r, "2 klyftor vitlök\n1 klyfta vitlök")
    assert r.ingredient_text().splitlines() == ["2 klyftor vitlök", "1 klyfta vitlök"]


def test_alias_implied_unit(seeded):
    r = Recipe.objects.create(name="T", servings=2)
    set_ingredients_from_text(r, "2 vitlöksklyftor\n1 vitlök\n3 klyftor vitlök")
    assert [(x.ingredient.name, x.unit) for x in r.ingredients.all()] == [
        ("Vitlök", "klyfta"),
        ("Vitlök", "st"),
        ("Vitlök", "klyfta"),
    ]


# ------------------------------------------------------------------- shopping list


def test_brief_example(seeded):
    plan("Vegobullar med potatismos", 0, 2)
    plan("Vegobullar med pasta och tomatsås", 3, 2)
    rows = rows_by_name(shopping.build(WEEK, "willys"))
    assert rows["Vegobullar"].quantity == "1 förp"
    assert len(rows["Vegobullar"].sources) == 2
    assert rows["Mjölig potatis"].quantity == "500 g"
    assert rows["Havredryck"].quantity == "2 dl"
    assert rows["Vegansk margarin"].quantity == "50 g"
    assert rows["Pasta"].quantity == "250 g"
    assert rows["Krossade tomater"].quantity == "1 förp"


def test_servings_scale_list(seeded):
    plan("Vegobullar med potatismos", 0, 4)  # the recipe is for 2
    plan("Vegobullar med potatismos", 1, 2)
    rows = rows_by_name(shopping.build(WEEK, "willys"))
    assert rows["Mjölig potatis"].quantity == "1,5 kg"
    assert rows["Vegobullar"].quantity == "2 förp"


def test_water_and_other_weeks_excluded(seeded):
    plan("Röd linssoppa med kokos", 0, 4)
    PlannedMeal.objects.create(
        date=WEEK + dt.timedelta(days=7), recipe=Recipe.objects.get(name="Tacos med vegofärs"), servings=4
    )
    rows = rows_by_name(shopping.build(WEEK, "willys"))
    assert "Vatten" not in rows
    assert "Tortillabröd" not in rows


def test_staples_listed_separately(seeded):
    plan("Chili sin carne", 0, 4)
    sl = shopping.build(WEEK, "willys")
    assert "Spiskummin" in {r.name for r in sl.staples}
    assert "Spiskummin" not in {r.name for r in sl.all_rows}


def test_removed_items(seeded):
    plan("Vegobullar med potatismos", 0, 2)
    potato = Ingredient.objects.get(name="Mjölig potatis")
    ShoppingItemState.objects.create(week=WEEK, ingredient=potato, removed=True)
    sl = shopping.build(WEEK, "willys")
    assert "Mjölig potatis" in {r.name for r in sl.removed}
    assert "Mjölig potatis" not in {r.name for r in sl.all_rows}


# ------------------------------------------------------------------- products


def test_parse_size():
    assert axfood.parse_size("300g") == (D("300"), "g")
    assert axfood.parse_size("1,5l") == (D("1500"), "ml")
    assert axfood.parse_size("ca: 1kg") == (D("1000"), "g")
    assert axfood.parse_size("4x125g") == (D("500"), "g")
    assert axfood.parse_size("") == (None, "")
    assert axfood.parse_size("380/230g") == (D("380"), "g")  # net weight, not drained
    assert axfood.parse_size("12p/6l") == (D("12"), "st")


def test_normalize():
    assert index.normalize("Tomater Krossade 3-pack") == "tomater krossade 3 pack"
    assert index.normalize("Imat Fraîche 15%") == "imat fraiche 15"
    assert index.normalize("Ärter Gröna") == "ärter gröna"


def test_match_rule_words_excludes_alternatives_and_categories(seeded):
    ing = Ingredient.objects.get(name="Krossade tomater")
    ing.match = "krossade tomat -chili; passata @skafferi/konserver"
    ing.save()
    product("a", "Tomater Krossade", "skafferi/konserver-och-burkar", "500g", willys="8")
    product("b", "Krossade Tomater Chili", "skafferi/konserver-och-burkar", "390g", willys="13")
    product("c", "Passata Rustica", "skafferi/konserver-och-burkar", "500g", willys="20")
    product("d", "Tomater Krossade", "frukt-och-gront/gronsaker", "500g", willys="8")  # wrong category
    product("e", "Okrossade tomater", "skafferi/konserver-och-burkar", "500g", willys="8")  # not at the start of a word
    assert {p.code for p in catalog.candidates(ing, "willys")} == {"a", "c"}


def test_only_checked_vegan_products_are_offered(seeded):
    tofu = Ingredient.objects.get(name="Tofu")
    product("v", "Tofu Naturell", "vegetariskt/tofu", "400g", willys="25")
    product("x", "Tofu med Ägg", "vegetariskt/tofu", "400g", willys="5", vegan=False)
    product("u", "Tofu Okänd", "vegetariskt/tofu", "400g", willys="4", vegan=None)
    assert [p.code for p in catalog.candidates(tofu, "willys")] == ["v"]
    assert [p.code for p in catalog.search("tofu", "willys")] == ["v"]


def test_cheapest_for_the_amount_is_chosen(seeded):
    """2.5 förp vegobullar (750 g): one 900 g family pack is cheaper than three small ones."""
    small = product("s", "Vegobullar Frysta", "fryst/vegetariskt", "300g", willys="43.90")
    big = product("b", "Vegobullar Frysta", "fryst/vegetariskt", "900g", willys="66.90")
    plan("Vegobullar med potatismos", 0, 2)  # 0.5 förp
    row = rows_by_name(shopping.build(WEEK, "willys"))["Vegobullar"]
    assert row.offer.product == small and row.cost == D("43.90")  # the small one is enough
    plan("Vegobullar med potatismos", 1, 4)  # + 1 förp
    plan("Vegobullar med potatismos", 2, 4)  # + 1 förp
    row = rows_by_name(shopping.build(WEEK, "willys"))["Vegobullar"]
    assert row.offer.product == big and row.offer.packages == 1 and row.cost == D("66.90")
    assert row.options == 2 and not row.chosen


def test_promo_applies_only_from_min_quantity(seeded):
    tofu = Ingredient.objects.get(name="Tofu")
    p = product("t", "Tofu Naturell", "vegetariskt/tofu", "400g", willys="25.90", promo=("20.00", 2))
    item = shopping.aggregate([shopping.Line(tofu.pk, D("1"), "förp")], {tofu.pk: tofu.facts()})[tofu.pk]
    o = catalog.offer(tofu, p, item, "willys")
    assert o.packages == 1 and o.cost == D("25.90") and not o.promo
    item = shopping.aggregate([shopping.Line(tofu.pk, D("2"), "förp")], {tofu.pk: tofu.facts()})[tofu.pk]
    o = catalog.offer(tofu, p, item, "willys")
    assert o.packages == 2 and o.cost == D("40.00") and o.promo


def test_product_weighing_about_one_piece_counts_as_one_piece(seeded):
    avocado = Ingredient.objects.get(name="Avokado")  # 200 g per piece in the seed data
    one = product("a", "Avokado Klass 1", "frukt-och-gront/gronsaker", "147g", willys="13.90")
    bag = product("b", "Avokado 3-pack", "frukt-och-gront/gronsaker", "600g", willys="34.90")
    item = shopping.aggregate([shopping.Line(avocado.pk, D("1"), "st")], {avocado.pk: avocado.facts()})[avocado.pk]
    assert catalog.offer(avocado, one, item, "willys").packages == 1  # not 2 (147 g < 200 g)
    item = shopping.aggregate([shopping.Line(avocado.pk, D("2"), "st")], {avocado.pk: avocado.facts()})[avocado.pk]
    assert catalog.offer(avocado, one, item, "willys").cost == D("27.80")
    assert catalog.offer(avocado, bag, item, "willys").packages == 1  # 600 g is enough for 2 × 200 g


def test_loose_weight_is_priced_per_kg(seeded):
    potato = Ingredient.objects.get(name="Mjölig potatis")
    loose = product("l", "Potatis Mjölig Klass 1", "frukt-och-gront/potatis-och-rotsaker", "", willys="14", per_kg=True)
    bag = product("p", "Potatis Mjölig Klass 1", "frukt-och-gront/potatis-och-rotsaker", "2kg", willys="27.90")
    plan("Vegobullar med potatismos", 0, 2)  # 500 g
    row = rows_by_name(shopping.build(WEEK, "willys"))["Mjölig potatis"]
    assert row.offer.product == loose and row.cost == D("7.00") and row.offer.packages is None
    assert row.offer.amount_text == "ca 500 g"
    assert bag in [o.product for o in catalog.offers(potato, None, "willys")]


def test_user_choice_overrides_cheapest_and_can_be_reset(seeded, client):
    cheap = product("c", "Tofu Billig", "vegetariskt/tofu", "400g", willys="20")
    fancy = product("f", "Tofu Eko", "vegetariskt/tofu", "400g", willys="30")
    plan("Tofuwok med nudlar", 0, 4)
    tofu = Ingredient.objects.get(name="Tofu")
    assert rows_by_name(shopping.build(WEEK, "willys"))["Tofu"].offer.product == cheap

    r = client.get(f"/handla/{WEEK}/rad/{tofu.pk}/vara/")
    assert r.status_code == 200 and "Tofu Eko" in r.content.decode()
    r = client.post(f"/handla/{WEEK}/rad/{tofu.pk}/vara/", {"code": "f"})
    assert r["HX-Refresh"] == "true"
    row = rows_by_name(shopping.build(WEEK, "willys"))["Tofu"]
    assert row.offer.product == fancy and row.chosen

    client.post(f"/handla/{WEEK}/rad/{tofu.pk}/vara/", {"code": ""})
    assert rows_by_name(shopping.build(WEEK, "willys"))["Tofu"].offer.product == cheap


def test_choice_of_non_vegan_product_is_refused(seeded, client):
    product("x", "Inte vegansk", "vegetariskt/tofu", "400g", willys="1", vegan=False)
    tofu = Ingredient.objects.get(name="Tofu")
    client.post(f"/handla/{WEEK}/rad/{tofu.pk}/vara/", {"code": "x"})
    tofu.refresh_from_db()
    assert tofu.preferred_code == ""


def test_comparison_uses_same_products_at_other_chain(seeded):
    product("p", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="10", hemkop="12")
    product("t", "Tomater Krossade", "skafferi/konserver-och-burkar", "400g", willys="50")  # Willys only
    plan("Vegobullar med pasta och tomatsås", 0, 2)
    sl = shopping.build(WEEK, "willys")
    assert sl.total == D("60")
    assert sl.comparison == (D("10"), D("12"), 1)
    assert rows_by_name(sl)["Pasta"].other.cost == D("12")


def test_consumed_cost_uses_bought_product_size(seeded):
    tomato = Ingredient.objects.get(name="Krossade tomater")  # standard package 400 g
    p = product("3", "Tomater Krossade 3-pack", "skafferi/konserver-och-burkar", "1200g", willys="30")
    o = catalog.offer(tomato, p, None, "willys")
    assert shopping.consumed_cost(D("1"), "förp", tomato, o) == D("10")  # one third
    pasta = Ingredient.objects.get(name="Pasta")
    p = product("4", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="20")
    assert shopping.consumed_cost(D("200"), "g", pasta, catalog.offer(pasta, p, None, "willys")) == D("8")


def test_recipe_lines_and_cost(seeded):
    product("p", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="20")
    recipe = Recipe.objects.get(name="Vegobullar med pasta och tomatsås")
    lines, cost = shopping.recipe_lines(recipe, D(1), "willys")
    pasta = next(ln for ln in lines if ln.ingredient.name == "Pasta")
    assert pasta.offer.product.code == "p" and pasta.cost == D("10")  # 250 g of 500 g
    assert cost == D("10")


def test_extra_items(seeded, client):
    p = product("k", "Kaffe Mellanrost", "skafferi/kaffe", "450g", willys="49.90", hemkop="52.90")
    client.post(f"/handla/{WEEK}/extra/", {"code": "k"})
    client.post(f"/handla/{WEEK}/extra/", {"code": "k"})
    item = ExtraItem.objects.get()
    assert item.count == 2
    sl = shopping.build(WEEK, "willys")
    row = sl.all_rows[0]
    assert row.offer.product == p and row.cost == D("99.80") and row.other.cost == D("105.80")
    client.post(f"/handla/extra/{item.pk}/", {"action": "minus"})
    assert ExtraItem.objects.get().count == 1
    client.post(f"/handla/extra/{item.pk}/", {"action": "delete"})
    assert not ExtraItem.objects.exists()


# ------------------------------------------------------------------- index


def fake_store(monkeypatch, *, fail_hemkop=False):
    tree = {
        "willys": [
            {"url": "vegetariskt", "title": "Vegetariskt", "children": [{"url": "vegetariskt/tofu", "title": "Tofu"}]},
            {
                "url": "kott-chark-och-fagel",
                "title": "Kött",
                "children": [{"url": "kott-chark-och-fagel/kott", "title": "Kött"}],
            },
        ],
        "hemkop": [
            {"url": "vegetariskt", "title": "Vegetariskt", "children": [{"url": "vegetariskt/tofu", "title": "Tofu"}]}
        ],
    }
    listing = {
        ("willys", "vegetariskt/tofu"): [
            ProductData(
                "willys", "1_ST", "Tofu Naturell", size_text="400g", size_amount=D(400), size_unit="g", price=D("25.90")
            ),
            ProductData(
                "willys", "2_ST", "Tofu med Ägg", size_text="400g", size_amount=D(400), size_unit="g", price=D("19.90")
            ),
        ],
        ("hemkop", "vegetariskt/tofu"): [
            ProductData(
                "hemkop", "1_ST", "Tofu Naturell", size_text="400g", size_amount=D(400), size_unit="g", price=D("27.50")
            ),
            ProductData("hemkop", "9_ST", "Bara hos Hemköp", price=D("10")),
        ],
    }
    details = {
        "1_ST": Details("7310000000001", "Sojabönor, vatten. Kan innehålla spår av mjölk.", ""),
        "2_ST": Details("7310000000002", "Sojabönor, ÄGG", ""),
    }
    calls = []

    def list_category(retailer, slug):
        calls.append((retailer, slug))
        if fail_hemkop and retailer == "hemkop":
            raise axfood.StoreError("nere")
        yield from listing.get((retailer, slug), [])

    monkeypatch.setattr(axfood, "category_tree", lambda r: tree[r])
    monkeypatch.setattr(axfood, "list_category", list_category)
    monkeypatch.setattr(axfood, "fetch_details", lambda r, code: details[code])
    monkeypatch.setattr(index, "WILLYS_SECTIONS", {"vegetariskt": None})
    monkeypatch.setattr(index, "HEMKOP_SECTIONS", {"vegetariskt": None})
    monkeypatch.setattr(index, "MAX_ERRORS", 1)
    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: True)
    return calls


def test_index_run_builds_vegan_catalog(db, monkeypatch):
    calls = fake_store(monkeypatch)
    summary = index.run()
    assert ("willys", "kott-chark-och-fagel/kott") not in calls  # meat is skipped
    tofu = Product.objects.get(code="1_ST")
    assert tofu.vegan is True and tofu.ean == "7310000000001"  # a trace warning doesn't count
    assert tofu.category == "vegetariskt/tofu" and tofu.category_name == "Vegetariskt › Tofu"
    assert {p.retailer: p.price for p in tofu.prices.all()} == {"willys": D("25.90"), "hemkop": D("27.50")}
    assert Product.objects.get(code="2_ST").vegan is False
    assert not Product.objects.filter(code="9_ST").exists()  # Hemköp-only products are not included
    assert "1 veganska" in summary
    s = AppSettings.load()
    assert s.indexed_at and not s.index_running

    # Second run: no new detail requests, and expired prices disappear.
    monkeypatch.setattr(axfood, "fetch_details", lambda r, c: pytest.fail("ska inte granskas igen"))
    Price.objects.filter(product=tofu, retailer="willys").update(seen_at=timezone.now() - dt.timedelta(days=9))
    Price.objects.create(
        product=Product.objects.get(code="2_ST"),
        retailer="hemkop",
        price=1,
        seen_at=timezone.now() - dt.timedelta(days=9),
    )
    index.run(force_listings=True)
    assert not Price.objects.filter(product__code="2_ST", retailer="hemkop").exists()
    assert Price.objects.get(product=tofu, retailer="willys").seen_at > timezone.now() - dt.timedelta(minutes=1)


def test_visit_time_window_from_robots_txt():
    utc = dt.UTC
    assert axfood.CRAWL_DELAY == 10
    assert axfood.in_visit_time(dt.datetime(2026, 11, 8, 4, 0, tzinfo=utc))
    assert axfood.in_visit_time(dt.datetime(2026, 11, 8, 8, 44, tzinfo=utc))
    assert not axfood.in_visit_time(dt.datetime(2026, 11, 8, 8, 45, tzinfo=utc))
    assert not axfood.in_visit_time(dt.datetime(2026, 11, 8, 12, 0, tzinfo=utc))
    assert axfood.next_visit_time(dt.datetime(2026, 11, 8, 12, 0, tzinfo=utc)) == dt.datetime(
        2026, 11, 9, 4, 0, tzinfo=utc
    )
    assert axfood.next_visit_time(dt.datetime(2026, 11, 8, 2, 0, tzinfo=utc)) == dt.datetime(
        2026, 11, 8, 4, 0, tzinfo=utc
    )


def test_requests_are_paced_per_robots_txt(monkeypatch):
    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    slept = []
    monkeypatch.setattr(axfood.httpx, "get", lambda *a, **k: Reply())
    monkeypatch.setattr(axfood.time, "sleep", slept.append)
    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: True)
    axfood._last_call["willys"] = 0.0
    axfood._get("willys", "/a")
    axfood._get("willys", "/b")
    assert len(slept) == 1 and 9 < slept[0] <= 10  # the second request waited ~10 s


def test_product_links_point_at_the_chains_product_pages():
    assert (
        axfood.product_url("willys", "101233933_KG", "Bananer Ekologiska Klass 1")
        == "https://www.willys.se/produkt/Bananer-Ekologiska-Klass-1-101233933_KG"
    )
    assert (
        axfood.product_url("hemkop", "101_ST", "Havredryck Barista, Äpple")
        == "https://www.hemkop.se/produkt/Havredryck-Barista-Apple-101_ST"
    )
    assert axfood.product_url("willys", "101_ST") == "https://www.willys.se/produkt/101_ST"


def test_no_requests_outside_visit_time(db, monkeypatch):
    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: False)
    monkeypatch.setattr(axfood.httpx, "get", lambda *a, **k: pytest.fail("inget anrop utanför fönstret"))
    with pytest.raises(axfood.OutsideVisitTime):
        axfood.category_tree("willys")
    with pytest.raises(axfood.OutsideVisitTime):
        index.run()
    assert index.start_background() is False
    out = __import__("io").StringIO()
    call_command("index", stdout=out, stderr=out)
    assert "04:00–08:45 UTC" in out.getvalue()


def test_index_pauses_when_window_closes_and_resumes(db, monkeypatch):
    fake_store(monkeypatch)
    calls = {"n": 0}
    real = axfood.fetch_details

    def closing(retailer, code):
        calls["n"] += 1
        if calls["n"] == 2:
            raise axfood.OutsideVisitTime()
        return real(retailer, code)

    monkeypatch.setattr(axfood, "fetch_details", closing)
    summary = index.run()
    assert summary.startswith("Pausad") and "1 kvar" in summary
    assert Product.objects.filter(checked_at__isnull=False).count() == 1
    assert not AppSettings.load().index_running

    # Next run the same day: the listings are fresh, only the vetting continues.
    monkeypatch.setattr(axfood, "list_category", lambda r, s: pytest.fail("listningar är färska"))
    monkeypatch.setattr(axfood, "fetch_details", real)
    index.run()
    assert not Product.objects.filter(checked_at__isnull=True).exists()


def test_products_needed_by_ingredients_are_checked_first(seeded):
    other = product("o", "Bamboo Shoots", "skafferi/asien", "200g", willys="15", vegan=None)
    tofu = product("t", "Tofu Naturell", "vegetariskt/tofu", "400g", willys="25", vegan=None)
    assert index._matching_ingredients_first([other.pk, tofu.pk]) == [tofu.pk, other.pk]


def test_index_running_elsewhere_is_detected_and_not_started_twice(db, monkeypatch):
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(index_running=True, index_heartbeat=timezone.now())
    assert index.is_running() and index.start_background() is False
    # A run that has gone silent (the process died) no longer counts as running.
    AppSettings.objects.filter(pk=1).update(index_heartbeat=timezone.now() - dt.timedelta(minutes=10))
    assert not index.is_running()


def test_store_error_during_index_keeps_app_working(seeded, client, monkeypatch):
    fake_store(monkeypatch, fail_hemkop=True)
    with pytest.raises(axfood.StoreError):
        index.run()
    s = AppSettings.load()
    assert s.index_error and not s.index_running
    assert Product.objects.filter(code="1_ST").exists()  # the Willys part was saved
    assert client.get("/sortiment/").status_code == 200
    assert "avbröts" in client.get("/sortiment/status/").content.decode()


# ------------------------------------------------------------------- import


def test_import_jsonld():
    page = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"WebPage"},
      {"@type":"Recipe","name":"Linsgryta","recipeYield":"4 portioner","totalTime":"PT1H15M",
       "recipeIngredient":["2 dl röda linser","1 gul lök"],
       "recipeInstructions":[{"@type":"HowToStep","text":"Koka."},{"@type":"HowToStep","text":"Ät."}],
       "image":["https://ex.se/a.jpg"]}]}</script></html>"""
    r = importer.parse_html(page)
    assert r.name == "Linsgryta" and r.servings == 4 and r.minutes == 75
    assert r.ingredients == ["2 dl röda linser", "1 gul lök"]
    assert r.instructions == "1. Koka.\n2. Ät."
    assert r.image_url == "https://ex.se/a.jpg"


def test_import_without_recipe_raises():
    with pytest.raises(importer.ImportError_):
        importer.parse_html("<html></html>")


# ------------------------------------------------------------------- views


def test_pages_render(seeded, client):
    product("p", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="10", hemkop="12")
    plan("Chili sin carne", 0, 4)
    plan("Vegobullar med pasta och tomatsås", 1, 2)
    ExtraItem.objects.create(week=WEEK, product=Product.objects.get(code="p"))
    r = Recipe.objects.first()
    pasta = Ingredient.objects.get(name="Pasta")
    week = week_start(dt.date.today()).isoformat()
    for url in [
        "/recept/",
        "/recept/?q=tofu",
        "/recept/ny/",
        f"/recept/{r.pk}/",
        f"/recept/{r.pk}/?portioner=7",
        f"/recept/{r.pk}/redigera/",
        "/recept/importera/",
        f"/vecka/{WEEK}/",
        f"/vecka/{WEEK}/sammanfattning/",
        f"/handla/{WEEK}/",
        f"/handla/{WEEK}/rad/{pasta.pk}/vara/?q=fusilli",
        f"/handla/{WEEK}/extra/sok/?q=pasta",
        f"/maltid/valj/?date={week}",
        "/sortiment/",
        "/sortiment/?q=pasta",
        "/sortiment/?kategori=skafferi/pasta-ris-och-matgryn",
        "/sortiment/?kategori=skafferi",
        "/sortiment/status/",
    ]:
        assert client.get(url).status_code == 200, url
    assert client.get("/").status_code == 302


def test_shopping_page_shows_chosen_product_and_other_chain(seeded, client):
    product("p", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="10", hemkop="12")
    plan("Vegobullar med pasta och tomatsås", 0, 2)
    html = client.get(f"/handla/{WEEK}/").content.decode()
    assert "Fusilli Pasta" in html and "10,00 kr" in html and "Hemköp 12,00 kr" in html


def test_category_tree_and_top_level_filter(db, client):
    product("a", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="10")
    product("b", "Röda Linser", "skafferi/torra-baljvaxter", "500g", willys="20")
    product("c", "Gurka", "frukt-och-gront/gronsaker", "300g", willys="9")
    product("x", "Inte vegansk", "skafferi/torra-baljvaxter", "1kg", willys="1", vegan=False)
    Product.objects.filter(code="a").update(category_name="Skafferi › Pasta, ris & matgryn")
    Product.objects.filter(code__in=["b", "x"]).update(category_name="Skafferi › Torra baljväxter")
    Product.objects.filter(code="c").update(category_name="Frukt & Grönt › Grönsaker")
    tree = {t.slug: t for t in catalog.category_tree("willys")}
    assert tree["skafferi"].count == 2 and [c.name for c in tree["skafferi"].children] == [
        "Pasta, ris & matgryn",
        "Torra baljväxter",
    ]
    html = client.get("/sortiment/?kategori=skafferi").content.decode()
    assert "Fusilli Pasta" in html and "Röda Linser" in html and "Gurka</strong>" not in html
    html = client.get("/sortiment/?kategori=skafferi/torra-baljvaxter").content.decode()
    assert "Skafferi › Torra baljväxter" in html and "Fusilli Pasta" not in html


def test_set_retailer(seeded, client):
    client.post("/handla/butik/", {"retailer": "hemkop", "next": f"/handla/{WEEK}/"})
    assert AppSettings.load().retailer == "hemkop"
    client.post("/handla/butik/", {"retailer": "ica"})
    assert AppSettings.load().retailer == "hemkop"


def test_planner_flow_remembers_servings(seeded, client):
    r = Recipe.objects.get(name="Chili sin carne")
    day = WEEK.isoformat()
    resp = client.post("/maltid/ny/", {"date": day, "recipe": r.pk, "servings": 3})
    assert resp.status_code == 200 and resp["HX-Trigger"] == "plan-changed"
    assert AppSettings.load().default_servings == 3
    meal = PlannedMeal.objects.get()
    client.post(f"/maltid/{meal.pk}/portioner/", {"delta": 1})
    meal.refresh_from_db()
    assert meal.servings == 4
    thursday = (WEEK + dt.timedelta(days=3)).isoformat()
    client.post("/maltid/flytta/", {"id": meal.pk, "date": thursday, "order": str(meal.pk)})
    meal.refresh_from_db()
    assert meal.date.isoformat() == thursday
    client.post(f"/maltid/{meal.pk}/ta-bort/")
    assert not PlannedMeal.objects.exists()


def test_recipe_create_via_form(seeded, client):
    resp = client.post(
        "/recept/ny/",
        {
            "name": "Snabbsallad",
            "servings": 2,
            "ingredient_text": "1 gurka\n2 tomater",
            "instructions": "",
            "description": "",
        },
    )
    assert resp.status_code == 302
    assert Recipe.objects.get(name="Snabbsallad").ingredients.count() == 2


def test_ingredient_preview_shows_product(seeded, client):
    product("p", "Fusilli Pasta", "skafferi/pasta-ris-och-matgryn", "500g", willys="10")
    html = client.post("/recept/tolka/", {"ingredient_text": "250 g pasta\n1 drakfrukt\nsalt"}).content.decode()
    assert "Fusilli Pasta" in html and "ny ingrediens" in html and "basvara" in html


def test_every_category_has_store_categories_except_other(seeded):
    for c in Category.objects.exclude(name="Övrigt"):
        assert c.store_categories, c.name


def test_default_crawl_covers_all_food_but_no_non_food():
    tree = [
        {"url": u, "title": u, "children": [{"url": f"{u}/x", "title": "x"}]}
        for u in ("fryst", "kott-chark-och-fagel", "fisk-och-skaldjur", "dryck", "tobak")
    ]
    tree.append(
        {
            "url": "halsa-och-skonhet",
            "title": "Hälsa & Skönhet",
            "children": [
                {"url": "halsa-och-skonhet/harvard", "title": "Hårvård"},
                {"url": "halsa-och-skonhet/halsokost", "title": "Hälsokost"},
            ],
        }
    )
    slugs = [s for s, _ in index.resolve_sections(tree, None)]
    assert slugs == [
        "fryst/x",
        "kott-chark-och-fagel/x",
        "fisk-och-skaldjur/x",
        "dryck/x",
        "halsa-och-skonhet/halsokost",  # health food is food; hair care is not
    ]
    assert [s for s, _ in index.resolve_sections(tree, {"fryst": None})] == ["fryst/x"]
