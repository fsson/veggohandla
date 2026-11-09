import pytest


@pytest.fixture(autouse=True)
def _no_image_downloads(monkeypatch):
    """Tests never download images (seeding would otherwise fetch the recipe photos)."""
    from core.services import importer

    monkeypatch.setattr(importer, "download_image", lambda url, max_bytes=0: None)


def R(name, servings, minutes, ingredients, instructions, description=""):
    return {"name": name, "servings": servings, "minutes": minutes, "ingredients": ingredients.strip()}


# Recipes that used to be seed data and that the tests rely on (the seed now has only 5).
TEST_RECIPES = [
    R(
        "Vegobullar med pasta och tomatsås",
        2,
        25,
        """
0,5 förp vegobullar
250 g pasta
1 förp krossade tomater
1 gul lök, finhackad
2 klyftor vitlök
1 msk olivolja
Salt
Svartpeppar
""",
        """
Koka pastan enligt förpackningen.
Fräs lök och vitlök i olivolja. Tillsätt krossade tomater och låt puttra 10 minuter.
Bryn vegobullarna och vänd ner dem i såsen. Smaka av med salt och peppar.
""",
        "Snabb vardagspasta med krämig tomatsås.",
    ),
    R(
        "Tacos med vegofärs",
        4,
        25,
        """
400 g vegofärs
1 förp tacokrydda
8 tortillabröd
1 isbergssallad
2 tomater
1 gurka
1 avokado
1 förp majs
1 rödlök
1 förp tacosås
2 dl havrefraiche
100 g vegansk riven ost
""",
        """
Stek vegofärsen, tillsätt tacokrydda och lite vatten. Låt koka ihop.
Hacka grönsakerna och skiva avokadon.
Värm tortillabröden och duka fram allt.
""",
    ),
    R(
        "Tofuwok med nudlar",
        4,
        25,
        """
1 förp tofu
250 g risnudlar
1 förp wokgrönsaker
3 msk soja
1 msk sesamolja
2 klyftor vitlök
20 g ingefära
2 msk sweet chilisås
1 msk rapsolja
0,5 knippe salladslök
""",
        """
Pressa tofun torr och skär i tärningar. Stek gyllene i rapsolja.
Koka eller blötlägg nudlarna enligt förpackningen.
Woka grönsaker, vitlök och ingefära på hög värme.
Vänd ner nudlar, tofu, soja, sesamolja och sweet chili. Toppa med salladslök.
""",
    ),
]


def add_test_recipes():
    from core.models import Recipe
    from core.services.recipes import set_ingredients_from_text

    for r in TEST_RECIPES:
        if not Recipe.objects.filter(name=r["name"]).exists():
            recipe = Recipe.objects.create(name=r["name"], servings=r["servings"], minutes=r["minutes"])
            set_ingredients_from_text(recipe, r["ingredients"])
