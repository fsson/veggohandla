from decimal import Decimal as D

import pytest

from core.domain.aggregate import Line, aggregate, scale
from core.domain.parse import parse_line
from core.domain.units import (
    MASS,
    PACKAGE,
    PIECE,
    VOLUME,
    IngredientFacts,
    conversion_factor,
    format_number,
    format_quantity,
    packages_needed,
    to_base,
)

# ------------------------------------------------------------------ units


@pytest.mark.parametrize(
    ("amount", "unit", "expected"),
    [
        (D("2"), "dl", (D("200"), VOLUME)),
        (D("1.5"), "kg", (D("1500"), MASS)),
        (D("1"), "msk", (D("15"), VOLUME)),
        (D("3"), "st", (D("3"), PIECE)),
        (D("0.5"), "förp", (D("0.5"), PACKAGE)),
        (D("2"), "", (D("2"), PIECE)),
        (D("2"), "klyfta", (D("2"), "klyfta")),
    ],
)
def test_to_base(amount, unit, expected):
    assert to_base(amount, unit) == expected


def test_format_number_swedish():
    assert format_number(D("1.50")) == "1,5"
    assert format_number(D("2.000")) == "2"
    assert format_number(D("0.333333")) == "0,33"
    assert format_number(D("1000")) == "1000"


@pytest.mark.parametrize(
    ("amount", "dim", "expected"),
    [
        (D("1000"), MASS, "1 kg"),
        (D("250"), MASS, "250 g"),
        (D("1500"), VOLUME, "1,5 l"),
        (D("200"), VOLUME, "2 dl"),
        (D("30"), VOLUME, "2 msk"),
        (D("10"), VOLUME, "2 tsk"),
        (D("3"), PIECE, "3 st"),
        (D("1"), PACKAGE, "1 förp"),
    ],
)
def test_format_quantity(amount, dim, expected):
    assert format_quantity(amount, dim) == expected


def test_conversion_via_ingredient_facts():
    facts = IngredientFacts(grams_per_piece=D("150"), package_amount=D("2000"), package_dimension=MASS)
    assert conversion_factor(PIECE, MASS, facts) == D("150")
    # st -> g -> förp (two steps)
    assert conversion_factor(PIECE, PACKAGE, facts) == D("150") / D("2000")
    assert conversion_factor(VOLUME, MASS, facts) is None


def test_packages_needed():
    assert packages_needed(D("200"), D("500")) == 1
    assert packages_needed(D("500"), D("500")) == 1
    assert packages_needed(D("501"), D("500")) == 2
    assert packages_needed(D(1) / 3 * 3, D(1)) == 1  # rounding error
    assert packages_needed(D("0"), D("500")) == 0


# ------------------------------------------------------------------ parsing


@pytest.mark.parametrize(
    ("line", "qty", "unit", "name", "note"),
    [
        ("500 g mjölig potatis", D("500"), "g", "mjölig potatis", ""),
        ("500g mjölig potatis", D("500"), "g", "mjölig potatis", ""),
        ("1,5 dl havredryck", D("1.5"), "dl", "havredryck", ""),
        ("0.5 förp vegobullar", D("0.5"), "förp", "vegobullar", ""),
        ("1/2 paket vegobullar", D("0.5"), "förp", "vegobullar", ""),
        ("1 1/2 dl vatten", D("1.5"), "dl", "vatten", ""),
        ("½ citron", D("0.5"), "st", "citron", ""),
        ("1½ msk soja", D("1.5"), "msk", "soja", ""),
        ("2 gula lökar, finhackade", D("2"), "st", "gula lökar", "finhackade"),
        ("2-3 klyftor vitlök", D("3"), "klyfta", "vitlök", ""),
        ("1 burk krossade tomater (400 g)", D("1"), "förp", "krossade tomater", "400 g"),
        ("Salt och peppar", None, "", "Salt och peppar", ""),
        ("ca 200 g tofu", D("200"), "g", "tofu", ""),
        ("- 2 Msk. olivolja", D("2"), "msk", "olivolja", ""),
    ],
)
def test_parse_line(line, qty, unit, name, note):
    p = parse_line(line)
    assert p is not None
    assert (p.quantity, p.unit, p.name, p.note) == (qty, unit, name, note)


def test_parse_empty():
    assert parse_line("   ") is None


# ------------------------------------------------------------------ scaling


def test_scale():
    assert scale(D("500"), 4, 2) == D("250")
    assert scale(D("1"), 4, 6) == D("1.5")
    assert scale(None, 4, 2) is None
    with pytest.raises(ValueError):
        scale(D("1"), 0, 2)


# ------------------------------------------------------------------ aggregation

POTATO, MEATBALLS, OATMILK, PASTA, TOMATO, SALT, ONION = range(1, 8)


def test_example_from_brief():
    """The example from the original brief: two half packages of vegobullar become one package."""
    lines = [
        Line(POTATO, D("500"), "g", "mon"),
        Line(MEATBALLS, D("0.5"), "förp", "mon"),
        Line(OATMILK, D("2"), "dl", "mon"),
        Line(MEATBALLS, D("0.5"), "förp", "thu"),
        Line(PASTA, D("250"), "g", "thu"),
        Line(TOMATO, D("1"), "förp", "thu"),
    ]
    items = aggregate(lines)
    assert items[MEATBALLS].display() == "1 förp"
    assert items[MEATBALLS].packages == 1
    assert items[MEATBALLS].sources == ["mon", "thu"]
    assert items[POTATO].display() == "500 g"
    assert items[OATMILK].display() == "2 dl"


def test_mass_sums_and_converts_to_kg():
    items = aggregate([Line(POTATO, D("500"), "g"), Line(POTATO, D("500"), "g")])
    assert items[POTATO].display() == "1 kg"
    items = aggregate([Line(POTATO, D("300"), "g"), Line(POTATO, D("300"), "g")])
    assert items[POTATO].display() == "600 g"
    items = aggregate([Line(OATMILK, D("1"), "msk"), Line(OATMILK, D("1"), "msk")])
    assert items[OATMILK].display() == "2 msk"
    items = aggregate([Line(POTATO, D("500"), "g"), Line(POTATO, D("0.5"), "kg")])
    assert items[POTATO].display() == "1 kg"


def test_incompatible_units_kept_separate():
    items = aggregate([Line(POTATO, D("500"), "g"), Line(POTATO, D("2"), "st")])
    assert items[POTATO].display() == "500 g + 2 st"
    assert items[POTATO].packages is None


def test_incompatible_units_merged_with_facts():
    facts = {POTATO: IngredientFacts(grams_per_piece=D("150"))}
    items = aggregate([Line(POTATO, D("500"), "g"), Line(POTATO, D("2"), "st")], facts)
    assert items[POTATO].display() == "800 g"


def test_package_merges_with_mass():
    facts = {MEATBALLS: IngredientFacts(package_amount=D("300"), package_dimension=MASS)}
    items = aggregate([Line(MEATBALLS, D("0.5"), "förp"), Line(MEATBALLS, D("200"), "g")], facts)
    assert items[MEATBALLS].display() == "350 g"
    assert items[MEATBALLS].packages == 2


def test_package_estimate_from_mass():
    facts = {PASTA: IngredientFacts(package_amount=D("500"), package_dimension=MASS)}
    items = aggregate([Line(PASTA, D("200"), "g"), Line(PASTA, D("250"), "g")], facts)
    assert items[PASTA].packages == 1
    items = aggregate([Line(PASTA, D("400"), "g"), Line(PASTA, D("250"), "g")], facts)
    assert items[PASTA].packages == 2


def test_volume_mix_picks_readable_unit():
    items = aggregate([Line(OATMILK, D("2"), "dl"), Line(OATMILK, D("3"), "msk")])
    assert items[OATMILK].display() == "2,45 dl"
    items = aggregate([Line(OATMILK, D("8"), "dl"), Line(OATMILK, D("0.5"), "l")])
    assert items[OATMILK].display() == "1,3 l"


def test_pieces_rounded_up_for_shopping():
    items = aggregate([Line(ONION, D("0.75"), "st"), Line(ONION, D("1"), "st")])
    assert items[ONION].display() == "2 st"


def test_unquantified():
    items = aggregate([Line(SALT, None, "")])
    assert items[SALT].unquantified
    assert items[SALT].display() == ""
    items = aggregate([Line(SALT, None, ""), Line(SALT, D("1"), "tsk")])
    assert not items[SALT].unquantified
    assert items[SALT].display() == "1 tsk"


def test_no_merge_across_ingredient_ids():
    items = aggregate([Line(1, D("1"), "st"), Line(2, D("1"), "st")])
    assert set(items) == {1, 2}


def test_signature_changes_with_amount():
    a = aggregate([Line(PASTA, D("200"), "g")])[PASTA].signature()
    b = aggregate([Line(PASTA, D("400"), "g")])[PASTA].signature()
    assert a != b
    assert a == aggregate([Line(PASTA, D("0.2"), "kg")])[PASTA].signature()


def test_scaling_then_aggregation():
    # Recipe for 4 planned for 2 + recipe for 2 planned for 4
    lines = [
        Line(PASTA, scale(D("500"), 4, 2), "g"),
        Line(PASTA, scale(D("100"), 2, 4), "g"),
    ]
    assert aggregate(lines)[PASTA].display() == "450 g"


def test_plural_units():
    assert format_quantity(D("2"), "klyfta") == "2 klyftor"
    assert format_quantity(D("1"), "klyfta") == "1 klyfta"
    assert format_quantity(D("0.5"), "knippe") == "0,5 knippe"


def test_purchase_package_does_not_change_recipe_package():
    """'1 förp krossade tomater' = 400 g even when buying a 3-pack of 1170 g."""
    facts = {
        TOMATO: IngredientFacts(
            package_amount=D("400"),
            package_dimension=MASS,
            purchase_amount=D("1170"),
            purchase_dimension=MASS,
        )
    }
    items = aggregate([Line(TOMATO, D("1"), "förp"), Line(TOMATO, D("400"), "g")], facts)
    assert items[TOMATO].display() == "800 g"
    assert items[TOMATO].packages == 1  # one 3-pack is enough
    items = aggregate(
        [Line(TOMATO, D("3"), "förp")],
        {
            TOMATO: IngredientFacts(
                package_amount=D("400"), package_dimension=MASS, purchase_amount=D("250"), purchase_dimension=MASS
            )
        },
    )
    assert items[TOMATO].packages == 5  # 1200 g / 250 g


# ------------------------------------------------------------------ vegan

from core.domain.vegan import animal_word, classify  # noqa: E402


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Vatten, havre 10%, rapsolja, salt. Kan innehålla spår av mjölk.", None),
        ("Tillverkad i en fabrik som även hanterar ägg och mjölk.", None),
        ("Vetemjöl, SKUMMJÖLKSPULVER, socker", "skummjölkspulver"),
        ("Pasta (durumvete), ägg", "ägg"),
        ("Kokosmjölk 60%, vatten, kakaosmör, jordnötssmör", None),
        ("Mjölksyrabakterier, sojabönor, mjölksyra", None),
        ("Mjukost, salt", "mjukost"),
        ("Äppelmost, socker, rostad lök, kostfiber", None),
        ("Linfrön (flax), salt", None),
        ("Socker, honung", "honung"),
        ("Vatten, tonfisk", "tonfisk"),
        ("Färgämne (E120)", "e120"),
        ("Vitamin D3", "d3"),
        ("Glucose syrup, WHEY powder", "whey"),
        ("Majsstärkelse, vasslepulver", "vasslepulver"),
        ("Gelatin", "gelatin"),
        ("Vete. Kan innholde/innehålla EGG/ÄGG/ÆG, MELK/MJÖLK.", None),  # Norwegian trace warning
        ("Dadlar. Ei sovellu alle 3-vuotiaille lapsille.", None),  # Finnish, not "sill"
        ("Persille, salt", None),
        ("Skyddad geografisk beteckning", None),
        ("Inlagd matjessill", "matjessill"),
        ("Torsk (FISK)", "fisk"),
    ],
)
def test_animal_word(text, hit):
    assert animal_word(text) == hit


def test_classify_is_strict():
    assert classify("Vegan", "Sojabönor, vatten", "vegetariskt/tofu")[0] is True
    assert classify("Vegan", "", "skafferi/x")[0] is True  # the chain's labelling is enough
    assert classify("", "Durumvete, vatten", "skafferi/pasta")[0] is True
    assert classify("", "Vetemjöl, ÄGG", "skafferi/pasta") == (False, "contains:ägg")
    # Without an ingredient list: only fruit and vegetables count as vegan.
    assert classify("", "", "frukt-och-gront/svamp", "Ostronskivling")[0] is True
    assert classify("", "", "frukt-och-gront/frukt", "Honungsmelon")[0] is True
    assert classify("", "", "skafferi/kryddor", "Salt")[0] is None


def test_classify_needs_the_vegan_label_in_meat_and_fish():
    assert classify("", "", "kott-chark-och-fagel/kott", "Ryggbiff") == (None, "label_required")
    assert classify("", "Ärtprotein, rapsolja", "fisk-och-skaldjur/palagg") == (None, "label_required")
    assert classify("", "Nötkött 100%", "kott-chark-och-fagel/kott") == (False, "contains:nötkött")
    assert classify("Vegansk", "Ärtprotein, rapsolja", "kott-chark-och-fagel/palagg") == (True, "labelled")


def test_vitamin_d3_is_animal_unless_labelled_vegan():
    assert classify("", "Kalcium, kolekalciferol", "halsa-och-skonhet/halsokost")[0] is False
    assert classify("Vegan", "Kalcium, kolekalciferol (från lav)", "halsa-och-skonhet/halsokost")[0] is True


from core.domain.aggregate import AggregatedItem, merge_with  # noqa: E402


def test_merge_with_product_size():
    """'1 förp + 200 g' can only be merged once the product's size is known."""
    item = AggregatedItem(1, {PACKAGE: D("1"), MASS: D("200")})
    facts = IngredientFacts(
        package_amount=D("500"), package_dimension=MASS, purchase_amount=D("500"), purchase_dimension=MASS
    )
    merged = merge_with(item, facts)
    assert merged.amounts == {MASS: D("700")} and merged.packages == 2
    assert item.amounts == {PACKAGE: D("1"), MASS: D("200")}  # the original is untouched
