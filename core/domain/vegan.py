"""Strict vegan check of a product based on the chain's labelling and ingredient list.

The principle is to rather exclude a vegan product than let an animal one in:

  * labelled "Vegan" by the chain            -> vegan
  * ingredient list without animal words     -> vegan
  * animal word in the ingredient list       -> not vegan
  * no ingredient list                       -> vegan only for unprocessed fruit/veg,
                                                otherwise unknown (and not shown)

Trace warnings ("kan innehålla spår av mjölk") don't count – they are about allergy,
not about contents.

The word lists are Swedish (plus Norwegian, Danish, Finnish and English) because they
are matched against the ingredient lists printed on Swedish store products.
"""

from __future__ import annotations

import re

# Word stems that count anywhere inside a word ("skummjölkspulver", "äggula", "tonfisk").
ANIMAL_PARTS = (
    "mjölk",
    "grädd",
    "smör",
    "vassle",
    "kasein",
    "laktos",
    "ägg",
    "honung",
    "gelatin",
    "kött",
    "fläsk",
    "kyckling",
    "kalkon",
    "bacon",
    "skinka",
    "ansjovis",
    "sardell",
    "karmin",
    "koschenill",
    "skaldjur",
    "bivax",
    "lanolin",
    "shellack",
    "schellack",
    "talg",
    "kollagen",
    "albumin",
    "lysozym",
    "yoghurt",
    "kvarg",
    "mozzarella",
    "parmesan",
    "cheddar",
    "halloumi",
    "mascarpone",
    "ricotta",
    "pecorino",
    "gouda",
    "räkor",
    "räka",
    "räkextrakt",
    "musslor",
    "mussla",
    "ostron",
    "krabba",
    "hummer",
    "kräft",
    "hönsbuljong",
    "hönsfond",
    "hönsfett",
    "nötbuljong",
    "nötfond",
    "nötfett",
    "nötkött",
    "oxfond",
    "kalvfond",
    "kalvkött",
    "lammkött",
    "lammfett",
    "ankfett",
    "svinfett",
    "svinister",
    "benmärg",
    "laxfil",
    "tonfisk",
    "ostpulver",
    "keso",
    "fetaost",
    "ghee",
    # English ingredient lists
    "whey",
    "casein",
    "lactose",
    "honey",
    "beeswax",
    "anchov",
    "fish",
    "beef",
    "pork",
    "chicken",
    "shrimp",
    "gelatine",
)
# Whole words (for short stems that would otherwise give false alarms).
ANIMAL_WORDS = {
    "ost",
    "ostar",
    "osten",
    "feta",
    "lamm",
    "anka",
    "lax",
    "ister",
    "egg",
    "eggs",
    "d3",
    "e120",
    "e441",
    "e542",
    "e901",
    "e904",
    "e913",
    "e966",
    "e1105",
}
# Words ending in "ost" are cheese ("mjukost", "getost") – except these.
NOT_CHEESE_OST = ("most", "rost", "frost", "kompost")

# Words that contain an animal stem but are vegan.
VEGAN_PREFIXES = (
    "kokosmjölk",
    "kokosgrädd",
    "kakaosmör",
    "sheasmör",
    "jordnötssmör",
    "mandelsmör",
    "nötsmör",
    "cashewsmör",
    "hasselnötssmör",
    "sesamsmör",
    "solrossmör",
    "mjölksyr",
    "havremjölk",
    "sojamjölk",
    "mandelmjölk",
    "rismjölk",
    "havregrädd",
    "sojagrädd",
    "smörgås",
    "mjölkfri",
    "äggfri",
    "laktosfri",
    "köttfri",
    "fiskfri",
    "smörgåsgurk",
    "sojayoghurt",
    "havreyoghurt",
    "kokosyoghurt",
    "växtbaserad",
    "mjölkfritt",
    "honungsmelon",
    "ostronskivling",
    "ostronsvamp",
    "smörsallad",
    "smörbön",
)
VEGAN_WORDS: set[str] = set()  # individual exceptions, extended as needed

_TRACE_RE = re.compile(
    # Swedish, Norwegian, Danish and Finnish trace warnings
    r"(kan (?:innehålla|inneholde|innholde|indeholde|sisältää)|kan förekomma|spår av|spor av|spor af|"
    r"innehåller spår|risk för spår|voi sisältää|tillverkad i en|"
    r"tillverkas i en|produceras i en|packad i en|packas i en|hanteras även|som även hanterar|"
    r"i samma (?:fabrik|lokal|anläggning))[^.;]*",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zåäöéü0-9]+", re.IGNORECASE)

# Store categories where products without an ingredient list are unprocessed plants.
PRODUCE_CATEGORIES = ("frukt-och-gront/",)


def animal_word(text: str) -> str | None:
    """First animal word in an ingredient text (ignoring trace warnings), otherwise None."""
    cleaned = _TRACE_RE.sub(" ", text or "")
    for word in _WORD_RE.findall(cleaned.lower()):
        if word in VEGAN_WORDS or word.startswith(VEGAN_PREFIXES):
            continue
        if word in ANIMAL_WORDS:
            return word
        if word.endswith("ost") and not word.endswith(NOT_CHEESE_OST) and len(word) > 4:
            return word
        if word.startswith("sill") or word.endswith("sill"):  # not "persille", "lapsille"
            return word
        if "fisk" in word and "grafisk" not in word:  # not "geografisk"
            return word
        for part in ANIMAL_PARTS:
            if part in word:
                return word
    return None


def classify(diet: str, ingredients: str, category: str, name: str = "") -> tuple[bool | None, str]:
    """(vegan?, reason code). None = unknown, treated as not vegan.

    The reason is a language-neutral code ("labelled", "no_animal", "produce", "no_list" or
    "contains:<word>") that the UI turns into text.
    """
    if diet and "vegan" in diet.lower():
        return True, "labelled"
    if ingredients and ingredients.strip():
        hit = animal_word(ingredients)
        if hit:
            return False, f"contains:{hit}"
        return True, "no_animal"
    if category.startswith(PRODUCE_CATEGORIES) and not animal_word(name):
        return True, "produce"
    return None, "no_list"
