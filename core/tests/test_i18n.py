"""Interface translation: Swedish is the source language, English the translation."""

import datetime as dt
import html
import re
import shutil
from decimal import Decimal as D
from pathlib import Path

import polib
import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils import translation

from core.domain.units import decimal_separator, format_number
from core.tests.conftest import add_test_recipes
from core.models import AppSettings, ExtraItem, Ingredient, PlannedMeal, Price, Product, Recipe
from core.services import index, shopping
from core.templatetags.vl import kr, kr_round, vegan_reason

WEEK = dt.date(2026, 11, 2)  # a Monday
PO = Path(settings.BASE_DIR) / "locale" / "en" / "LC_MESSAGES" / "django.po"
MO = PO.with_suffix(".mo")


@pytest.fixture
def seeded(db):
    call_command("seed", stdout=open("/dev/null", "w"))
    add_test_recipes()  # recipes the tests use besides the 5 seed recipes


@pytest.fixture
def english(client):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    return client


def make_product(code="p", name="Fusilli Pasta", category="skafferi/pasta-ris-och-matgryn", size="500g",
                 willys="10", hemkop="12"):
    from core.stores import axfood

    amount, unit = axfood.parse_size(size)
    p = Product.objects.create(
        code=code, name=name, category=category, category_name="Skafferi › Pasta, ris & matgryn",
        size_text=size, size_amount=amount, size_unit=unit, search_text=index.normalize(name), vegan=True,
        vegan_reason="no_animal",
    )
    from django.utils import timezone

    for retailer, price in (("willys", willys), ("hemkop", hemkop)):
        Price.objects.create(product=p, retailer=retailer, price=D(price), seen_at=timezone.now())
    return p


def plan(name, offset, servings):
    return PlannedMeal.objects.create(
        date=WEEK + dt.timedelta(days=offset), recipe=Recipe.objects.get(name=name), servings=servings
    )


# ------------------------------------------------------------ catalogue integrity


def test_every_message_is_translated_and_compiled():
    po = polib.pofile(str(PO))
    mo = polib.mofile(str(MO))
    compiled = {(e.msgctxt, e.msgid): e for e in mo}
    placeholder = re.compile(r"%\(\w+\)s")
    for e in po:
        assert "fuzzy" not in e.flags, f"fuzzy: {e.msgid!r}"
        # makemessages records the old source text ("#| msgid") when a text changes; an entry
        # that still has it was not reviewed and may carry the old translation.
        assert not e.previous_msgid, f"review the translation and remove '#| msgid': {e.msgid!r}"
        strings = list(e.msgstr_plural.values()) if e.msgid_plural else [e.msgstr]
        assert strings and all(s.strip() for s in strings), f"untranslated: {e.msgid!r}"
        for s in strings:
            assert sorted(placeholder.findall(s)) == sorted(placeholder.findall(e.msgid)), e.msgid
        assert (e.msgctxt, e.msgid) in compiled, f"missing in django.mo (run compilemessages): {e.msgid!r}"
        got = compiled[(e.msgctxt, e.msgid)]
        assert (got.msgstr_plural if e.msgid_plural else got.msgstr) == (e.msgstr_plural if e.msgid_plural else e.msgstr)


def test_catalogue_matches_the_code(monkeypatch):
    """Running makemessages would change nothing: every marked string is in the catalogue
    (templates included) and the catalogue holds no stale entries."""
    if not shutil.which("xgettext"):
        pytest.skip("GNU gettext is not installed")
    monkeypatch.chdir(settings.BASE_DIR)
    before = PO.read_bytes()
    keys = lambda path: {(e.msgctxt, e.msgid) for e in polib.pofile(str(path))}  # noqa: E731
    try:
        call_command("makemessages", locale=["en"], ignore_patterns=[".venv", "data", "docs"],
                     no_obsolete=True, no_location=True, verbosity=0)
        fresh = keys(PO)
    finally:
        PO.write_bytes(before)  # the test must not modify the repository
    PO.with_suffix(".po.tmp").unlink(missing_ok=True)
    catalogued = {(e.msgctxt, e.msgid) for e in polib.pofile(str(PO))}
    assert not (fresh - catalogued), f"new strings: run makemessages and translate {sorted(fresh - catalogued)}"
    assert not (catalogued - fresh), f"stale strings in the catalogue: {sorted(catalogued - fresh)}"


# ------------------------------------------------------------ language selection


def test_default_is_swedish_and_browser_language_is_honoured(seeded, client):
    assert "<html lang=\"sv\">" in client.get("/recept/").content.decode()
    r = client.get("/recept/", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert "<html lang=\"en\">" in r.content.decode()
    r = client.get("/recept/", headers={"Accept-Language": "de"})  # not offered -> Swedish
    assert "<html lang=\"sv\">" in r.content.decode()


def test_language_switch_sets_cookie_and_sticks(seeded, client):
    r = client.post("/i18n/setlang/", {"language": "en", "next": "/recept/"})
    assert r.status_code == 302 and r.url == "/recept/"
    assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == "en"
    html_en = client.get("/recept/").content.decode()
    assert "Search recipes or ingredients" in html_en
    client.post("/i18n/setlang/", {"language": "sv", "next": "/recept/"})
    assert "Sök recept eller ingrediens" in client.get("/recept/").content.decode()


def test_unknown_language_is_rejected(seeded, client):
    client.post("/i18n/setlang/", {"language": "klingon", "next": "/"})
    assert settings.LANGUAGE_COOKIE_NAME not in client.cookies


def test_switch_is_on_every_page(seeded, client):
    for url in ["/recept/", f"/vecka/{WEEK}/", f"/handla/{WEEK}/", "/sortiment/"]:
        page = client.get(url).content.decode()
        assert 'name="language" value="en"' in page and 'name="language" value="sv"' in page, url


# ------------------------------------------------------------ English pages


def test_english_pages_have_no_swedish_interface_text(seeded, english):
    make_product()
    p2 = make_product("k", "Kaffe Mellanrost", "skafferi/kaffe", "450g", willys="49.90", hemkop="52.90")
    plan("Vegobullar med pasta och tomatsås", 0, 2)
    plan("Chili sin carne", 2, 4)
    ExtraItem.objects.create(week=WEEK, product=p2)
    AppSettings.load()
    pasta = Ingredient.objects.get(name="Pasta")
    recipe = Recipe.objects.get(name="Chili sin carne")
    day = WEEK.isoformat()
    urls = [
        "/recept/", f"/recept/{recipe.pk}/", f"/recept/{recipe.pk}/?portioner=6", "/recept/ny/",
        f"/recept/{recipe.pk}/redigera/", "/recept/importera/", f"/vecka/{WEEK}/", f"/vecka/{WEEK}/sammanfattning/",
        f"/handla/{WEEK}/", f"/handla/{WEEK}/rad/{pasta.pk}/vara/", f"/handla/{WEEK}/rad/{pasta.pk}/vara/?q=zzz",
        f"/handla/{WEEK}/extra/sok/?q=kaffe", f"/handla/{WEEK}/extra/sok/?q=zzz", f"/maltid/valj/?date={day}",
        "/sortiment/", "/sortiment/?kategori=skafferi", "/sortiment/?q=zzz", "/sortiment/status/",
    ]
    po = polib.pofile(str(PO))
    swedish = [e.msgid for e in po if not e.msgid_plural and e.msgstr != e.msgid and len(e.msgid) >= 10
               and "%(" not in e.msgid]
    assert len(swedish) > 80  # the check is only meaningful if it covers the catalogue
    # Product, recipe and ingredient names are Swedish content; only the interface must translate.
    for url in urls:
        r = english.get(url)
        assert r.status_code == 200, url
        page = html.unescape(r.content.decode())
        assert "<html lang=\"en\">" in page or "<html" not in page
        for msgid in swedish:
            assert msgid not in page, f"{url}: untranslated {msgid!r}"


def test_english_planner_and_shopping_content(seeded, english):
    make_product()
    plan("Vegobullar med pasta och tomatsås", 0, 2)
    page = english.get(f"/vecka/{WEEK}/").content.decode()
    for text in ("Monday", "2 Nov", "Add", "items to buy", "To the shopping list", "Week 45"):
        assert text in page, text
    page = english.get(f"/handla/{WEEK}/").content.decode()
    assert "Shopping list" in page and "Check at home" in page and "Swap" in page
    assert "Hemköp 12.00 SEK" in page and "12,00 kr" not in page


def test_section_names_follow_the_language(seeded, english, client):
    make_product()
    plan("Vegobullar med pasta och tomatsås", 0, 2)
    assert "Pasta, rice &amp; dry goods" in english.get(f"/handla/{WEEK}/").content.decode()
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "sv"
    assert "Pasta, ris &amp; torrvaror" in client.get(f"/handla/{WEEK}/").content.decode()


def test_copy_text_is_translated(seeded):
    make_product()
    plan("Vegobullar med pasta och tomatsås", 0, 2)
    with translation.override("en"):
        text = shopping.build(WEEK, "willys").as_text()
    assert text.startswith("Shopping list, week 45") and "Check at home" in text
    assert shopping.build(WEEK, "willys").as_text().startswith("Inköpslista v. 45")


# ------------------------------------------------------------ numbers and prices


def test_prices_follow_the_language():
    with translation.override("sv"):
        assert kr(D("1234.5")) == "1 234,50 kr" and kr_round(D("1234.5")) == "1 234 kr"
    with translation.override("en"):
        assert kr(D("1234.5")) == "1,234.50 SEK" and kr_round(D("1234.5")) == "1,234 SEK"


def test_decimal_separator_follows_the_language(seeded, english, client):
    assert format_number(D("1.5")) == "1,5"  # default outside a request
    recipe = Recipe.objects.get(name="Vegobullar med pasta och tomatsås")  # has "0,5 förp vegobullar"
    assert "0.5 förp vegobullar" in english.get(f"/recept/{recipe.pk}/redigera/").content.decode()
    assert "0,5 förp vegobullar" in client.get(f"/recept/{recipe.pk}/redigera/", headers={"Accept-Language": "sv"}).content.decode()
    assert decimal_separator.get() == ","  # the request did not leak its setting


def test_english_recipe_text_roundtrips(seeded, english):
    """Saving a recipe whose amounts use a decimal point stores the same amounts."""
    recipe = Recipe.objects.get(name="Vegobullar med pasta och tomatsås")
    before = [(i.ingredient_id, i.quantity, i.unit) for i in recipe.ingredients.all()]
    page = english.get(f"/recept/{recipe.pk}/redigera/").content.decode()
    text = html.unescape(re.search(r'<textarea name="ingredient_text"[^>]*>(.*?)</textarea>', page, re.S).group(1))
    r = english.post(f"/recept/{recipe.pk}/redigera/", {
        "name": recipe.name, "servings": recipe.servings, "ingredient_text": text,
        "instructions": recipe.instructions, "description": "",
    })
    assert r.status_code == 302
    assert [(i.ingredient_id, i.quantity, i.unit) for i in recipe.ingredients.all()] == before


def test_english_messages(seeded, english):
    r = english.post("/recept/ny/", {"name": "Snabbsallad", "servings": 2, "ingredient_text": "1 gurka",
                                     "instructions": "", "description": ""}, follow=True)
    assert "“Snabbsallad” was saved." in html.unescape(r.content.decode())
    r = english.post("/recept/importera/", {"url": "ftp://x"})
    assert "Enter a web address" in r.content.decode()
    english.post("/vecka/2026-11-02/tom/")
    r = english.get("/vecka/2026-11-02/")
    assert "Cleared the week (0 meals)." in html.unescape(r.content.decode())


# ------------------------------------------------------------ data stored in the database


def test_vegan_reason_codes_are_translated_when_shown():
    with translation.override("sv"):
        assert vegan_reason("labelled") == "Märkt vegansk"
        assert vegan_reason("contains:ägg") == "Innehåller ”ägg”"
    with translation.override("en"):
        assert vegan_reason("labelled") == "Labelled vegan"
        assert vegan_reason("contains:ägg") == "Contains “ägg”"
        assert vegan_reason("no_animal") == "No animal ingredients"
        assert vegan_reason("something old") == "something old"  # unknown values pass through


def test_index_progress_is_stored_untranslated_and_shown_in_the_active_language(db):
    from django.utils.translation import gettext_noop

    AppSettings.load()
    index._set_progress(gettext_noop("Granskar ingredienser: %(i)s av %(n)s"), None, i=25, n=1600)
    raw = AppSettings.load().index_progress
    with translation.override("sv"):
        assert index.progress_text(raw) == "Granskar ingredienser: 25 av 1600"
    with translation.override("en"):
        assert index.progress_text(raw) == "Checking ingredients: 25 of 1600"
        assert index.progress_text("plain old text") == "plain old text"  # values stored before this change
        assert index.progress_text("") == ""
