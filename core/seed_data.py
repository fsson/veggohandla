"""Seed data: store sections, vegan ingredients and recipes.

The product matching (match=...) decides which products in the index count as the ingredient.
Recipes are written as plain ingredient text and go through the same parsing as when
typing a recipe in the app. The tests check that every line matches an ingredient below
(i.e. that no "new" ingredients are created when seeding).

Names, aliases and recipe text are Swedish on purpose: they are app content for Swedish stores.
"""

# (name, icon, order, Willys categories where the section's ingredients look for products)
# The order follows a typical path through the store.
CATEGORIES = [
    ("Frukt & grönt", "🥕", 10, "frukt-och-gront"),
    ("Bröd", "🍞", 20, "brod-och-kakor"),
    ("Kylt & mejerialternativ", "🥛", 30, "mejeri-ost-och-agg vegetariskt/palagg-och-ost fardigmat"),
    ("Veganskt", "🌱", 40, "vegetariskt fryst/vegetariskt mejeri-ost-och-agg/vegetariskt fardigmat/vegetariskt"),
    ("Frys", "❄️", 50, "fryst"),
    ("Pasta, ris & torrvaror", "🍝", 60,
     "skafferi/pasta-ris-och-matgryn skafferi/torra-baljvaxter skafferi/flingor-gryner-och-musli "
     "skafferi/asien skafferi/texmex skafferi/glutenfritt"),
    ("Konserver & burkar", "🥫", 70,
     "skafferi/konserver-och-burkar skafferi/sylt-mos-och-marmelad skafferi/texmex skafferi/asien"),
    ("Bakning", "🥣", 80, "skafferi/bakning"),
    ("Kryddor", "🧂", 90, "skafferi/kryddor-och-smaksattare skafferi/asien"),
    ("Oljor, såser & smaksättare", "🫙", 100,
     "skafferi/olja-och-vinager skafferi/kryddor-och-smaksattare skafferi/asien skafferi/texmex "
     "skafferi/oliver-och-delikatesser fardigmat/saser-grytbaser-och-ovriga-smaksattare"),
    ("Nötter & frön", "🥜", 110,
     "skafferi/bakning skafferi/torkad-frukt glass-godis-och-snacks skafferi/flingor-gryner-och-musli"),
    ("Övrigt", "📦", 999, ""),
]


def I(name, cat, pkg=None, gpp=None, gpdl=None, staple=False, aliases=(), shop=True, match=""):  # noqa: E741
    """match: rule for which products are the ingredient, see services/catalog.py (empty = the name)."""
    return {
        "name": name, "category": cat, "pkg": pkg, "gpp": gpp, "gpdl": gpdl,
        "staple": staple, "aliases": aliases, "shop": shop, "match": match,
    }


FG, BR, KY, VE, FR, TO, KO, BA, KR, OL, NO, OV = (c[0] for c in CATEGORIES)

INGREDIENTS = [
    # Fruit & vegetables
    I("Gul lök", FG, gpp=110, aliases=("gula lökar", "lök", "gul lökar"), match="lök gul"),
    I("Rödlök", FG, gpp=100, aliases=("rödlökar", "röd lök"), match="lök röd"),
    I("Vitlök", FG, gpp=50, aliases=(("vitlöksklyfta", "klyfta"), ("vitlöksklyftor", "klyfta"),
                                     ("vitlöksklyftan", "klyfta"), "vitlökar"), match="vitlök"),
    I("Mjölig potatis", FG, pkg="2 kg", gpp=100, aliases=("potatis mjölig", "mjöliga potatisar"), match="potatis mjölig"),
    I("Fast potatis", FG, pkg="1 kg", gpp=100, aliases=("potatis", "potatisar", "fasta potatisar"), match="potatis fast"),
    I("Sötpotatis", FG, gpp=350, aliases=("sötpotatisar",)),
    I("Morot", FG, pkg="1 kg", gpp=70, aliases=("morötter",), match="morot -kålmix; morötter"),
    I("Rödbeta", FG, gpp=120, aliases=("rödbetor",), match="rödbet -mangold"),
    I("Purjolök", FG, gpp=200, aliases=("purjolökar", "purjo")),
    I("Röd paprika", FG, gpp=160, aliases=("paprika", "paprikor", "röda paprikor"), match="paprika röd"),
    I("Tomat", FG, gpp=100, aliases=("tomater",), match="tomat -cocktail -baby -babyplommon -körsbär"),
    I("Körsbärstomater", FG, pkg="250 g", aliases=("körsbärstomat", "cocktailtomater"), match="cocktailtomat; tomat cocktail; tomater cocktail; körsbärstomat; tomater körsbär"),
    I("Gurka", FG, gpp=300, aliases=("gurkor",)),
    I("Zucchini", FG, gpp=250, aliases=("squash",)),
    I("Broccoli", FG, gpp=400, aliases=("broccolihuvud",)),
    I("Blomkål", FG, gpp=800, aliases=("blomkålshuvud",)),
    I("Babyspenat", FG, pkg="65 g", aliases=("färsk spenat", "spenat"), match="babyspenat; spenat"),
    I("Champinjoner", FG, pkg="250 g", aliases=("champinjon", "svamp")),
    I("Avokado", FG, gpp=200, aliases=("avokador", "avocado")),
    I("Citron", FG, gpp=120, aliases=("citroner",), match="citron -citrongräs -citronmeliss"),
    I("Lime", FG, gpp=70, aliases=("limefrukt", "limefrukter")),
    I("Ingefära", FG, aliases=("färsk ingefära", "riven ingefära")),
    I("Röd chili", FG, gpp=10, aliases=("chili", "färsk chili", "chilifrukt"), match="chili röd; chilipeppar; chili -reaper -carolina -habanero"),
    I("Salladslök", FG, aliases=("salladslökar",)),
    I("Isbergssallad", FG, gpp=400, aliases=("sallad", "isbergssalladshuvud"), match="sallad isberg; isberg -frisé"),
    I("Färsk koriander", FG, aliases=("koriander",), match="koriander"),
    I("Färsk basilika", FG, aliases=("basilika",), match="basilika"),
    I("Färsk persilja", FG, aliases=("persilja", "bladpersilja"), match="persilja"),
    # Bread
    I("Tortillabröd", BR, pkg="8 st", aliases=("tortillas", "tortilla", "mjuka tortillas"), match="tortilla -chips -strips -pockets @brod-och-kakor @skafferi/texmex"),
    I("Pitabröd", BR, pkg="6 st", aliases=("pitabröd fullkorn", "pita"), match="pitabröd; pita"),
    I("Surdegsbröd", BR, aliases=("bröd",)),
    # Chilled & dairy alternatives
    I("Havredryck", KY, pkg="1 l", gpdl=100, aliases=("havremjölk", "växtdryck", "mjölkfri dryck"), match="havredryck -choklad -vanilj -vaniljsmak -matcha -caramel -carame -hazeln -kanel -nötvan -pumpki -barista -ikaffe -fiber -deluxe"),
    I("Havregrädde", KY, pkg="2.5 dl", aliases=("havrebaserad matlagningsgrädde", "imat", "vegansk grädde", "matlagningsgrädde"), match="matlagningsgrädde; matlagningsbas; havregrädde; havremat; plant cream 15"),
    I("Havrefraiche", KY, pkg="2 dl", aliases=("vegansk crème fraiche", "vegansk creme fraiche", "havrebaserad fraiche"), match="fraiche"),
    I("Vegansk margarin", KY, pkg="600 g", aliases=("margarin", "mjölkfritt margarin", "mejerifritt margarin", "vegansk smör"), match="margarin; bredbart"),
    I("Vegansk riven ost", KY, pkg="150 g", aliases=("riven vegansk ost", "vegansk ost"), match="grate @vegetariskt/palagg-och-ost; riven vegansk"),
    I("Sojayoghurt", KY, pkg="1 kg", aliases=("vegansk yoghurt", "havregurt"), match="soygurt -vanilla -strawberry; kokosgurt; havregurt; sojayoghurt @mejeri-ost-och-agg"),
    I("Hummus", KY, pkg="200 g", match="hummus -karamelliserad -mix -soltorkad -tabbouleh @skafferi @fardigmat @mejeri-ost-och-agg"),
    # Vegetarian & tofu
    I("Vegobullar", VE, pkg="300 g", aliases=("veganska köttbullar", "vegobulle", "vegetariska bullar"), match="vegobullar; delikatessbullar; köttbullar köttfria"),
    I("Vegofärs", VE, pkg="1 kg", aliases=("sojafärs", "vegansk färs", "växtbaserad färs"), match="vegofärs; baljväxtfärs; formbar färs"),
    I("Tofu", VE, pkg="400 g", aliases=("fast tofu", "naturell tofu"), match="tofu -rökt -marinerad -sojamarinerad -friterad -crispy"),
    I("Rökt tofu", VE, pkg="200 g", match="tofu rökt; rökt tofu"),
    I("Vegobitar", VE, pkg="280 g", aliases=("sojabitar", "oumph", "vegostrimlor"), match="chunk -korean -bbq; strips; filet pieces; sojabitar"),
    # Frozen
    I("Gröna ärter", FR, pkg="500 g", gpdl=65, aliases=("ärter", "ärtor", "frysta ärter"), match="ärter -gula -morötter; ärtor -majs -gula"),
    I("Edamame", FR, pkg="400 g", gpdl=65, aliases=("edamamebönor", "sojabönor")),
    I("Wokgrönsaker", FR, pkg="600 g", aliases=("frysta wokgrönsaker",), match="wok"),
    I("Falafel", FR, pkg="400 g", aliases=("frysta falafel",)),
    I("Frysta blåbär", FR, pkg="750 g", gpdl=60, aliases=("blåbär", "frysta bär", "bär"), match="blåbär -hallon"),
    # Pasta, rice & dry goods
    I("Pasta", TO, pkg="500 g", aliases=("penne", "fusilli", "pastaskruvar"), match="fusilli; penne; makaroner; pasta -lasagneplattor -lasagne -glutenfri"),
    I("Spaghetti", TO, pkg="500 g"),
    I("Lasagneplattor", TO, pkg="500 g", aliases=("lasagneplatta",)),
    I("Jasminris", TO, pkg="1 kg", gpdl=85, aliases=("ris",)),
    I("Basmatiris", TO, pkg="1 kg", gpdl=85),
    I("Bulgur", TO, pkg="1 kg", gpdl=70, match="bulgur -nudlar"),
    I("Couscous", TO, pkg="500 g", gpdl=75),
    I("Quinoa", TO, pkg="500 g", gpdl=85, match="quinoa @skafferi/pasta-ris-och-matgryn"),
    I("Röda linser", TO, pkg="500 g", gpdl=85, aliases=("linser",), match="linser röda"),
    I("Gula ärtor", TO, pkg="500 g", gpdl=85, aliases=("torkade gula ärtor",), match="gula ärter; gula ärtor"),
    I("Havregryn", TO, pkg="1.5 kg", gpdl=35),
    I("Risnudlar", TO, pkg="250 g", aliases=("nudlar", "risnudlar breda"), match="risnudlar -tom"),
    I("Tacoskal", TO, pkg="12 st", match="taco shells; tacoskal @skafferi/texmex"),
    # Canned goods
    I("Krossade tomater", KO, pkg="400 g", aliases=("krossad tomat",), match="krossade tomat -chili -vitlök -örter -basilika -oliv"),
    I("Passerade tomater", KO, pkg="500 g", aliases=("passata",), match="passerade tomat -basilika -vitlök; passata"),
    I("Tomatpuré", KO, pkg="200 g", gpdl=100),
    I("Kikärtor", KO, pkg="380 g", aliases=("kikärter", "kokta kikärtor"), match="kikärt -tonfisk"),
    I("Svarta bönor", KO, pkg="380 g", aliases=("kokta svarta bönor",), match="bönor svarta"),
    I("Kidneybönor", KO, pkg="380 g", aliases=("röda kidneybönor", "röda bönor"), match="kidneybönor -chili"),
    I("Vita bönor", KO, pkg="380 g", aliases=("stora vita bönor", "cannellinibönor"), match="bönor vita -tomatsås -tomat -blandade"),
    I("Kokosmjölk", KO, pkg="400 ml", aliases=("kokosmjölk light",)),
    I("Majs", KO, pkg="300 g", aliases=("majskorn",), match="majskorn; majs -kolv -ärtor"),
    I("Tacosås", KO, pkg="230 g", aliases=("salsa",)),
    I("Lingonsylt", KO, pkg="400 g", aliases=("rårörda lingon",), match="lingonsylt; lingon rårörda; rårörda lingon"),
    I("Jordgubbssylt", KO, pkg="400 g", aliases=("sylt",)),
    # Baking
    I("Vetemjöl", BA, pkg="2 kg", gpdl=60, staple=True, aliases=("mjöl",)),
    I("Strösocker", BA, pkg="1 kg", gpdl=85, staple=True, aliases=("socker",)),
    I("Bakpulver", BA, staple=True),
    I("Majsstärkelse", BA, staple=True, aliases=("maizena", "majsstärkelse/maizena")),
    # Spices
    I("Salt", KR, staple=True, aliases=("flingsalt", "havssalt"), match="salt @skafferi/kryddor-och-smaksattare -ketchup -mindre -örtsalt -citronsalt"),
    I("Svartpeppar", KR, staple=True, aliases=("peppar", "svartpeppar malen", "nymalen svartpeppar")),
    I("Spiskummin", KR, staple=True, aliases=("spiskummin malen",)),
    I("Paprikapulver", KR, staple=True, match="paprikapulver -rökt"),
    I("Rökt paprikapulver", KR, staple=True, aliases=("rökt paprika",), match="rökt paprika"),
    I("Chiliflakes", KR, staple=True, aliases=("chili flakes", "torkad chili"), match="chili flakes -jalapeño -jalapeno -gochugaru"),
    I("Curry", KR, staple=True, aliases=("currypulver",), match="curry @skafferi/kryddor-och-smaksattare -sås -mangosås -currysås -thai"),
    I("Gurkmeja", KR, staple=True),
    I("Garam masala", KR, staple=True),
    I("Kanel", KR, staple=True, match="kanel malen; malen kanel"),
    I("Oregano", KR, staple=True, aliases=("torkad oregano",)),
    I("Timjan", KR, staple=True, aliases=("torkad timjan",)),
    I("Mejram", KR, staple=True, aliases=("torkad mejram",)),
    I("Lagerblad", KR, staple=True),
    I("Grönsaksbuljong", KR, staple=True, aliases=("grönsaksbuljongtärning", "buljongtärning", "grönsaksfond"), match="buljong grönsak; grönsaksbuljong; grönsak buljong; grönsaks buljong; vegetable fond"),
    I("Tacokrydda", KR, pkg="1 st", aliases=("tacokryddmix",), match="taco kryddmix -3; tacokrydda; spice mix taco @skafferi/texmex @skafferi/kryddor-och-smaksattare"),
    # Oils, sauces & condiments
    I("Olivolja", OL, staple=True, match="olivolja -raps -spray"),
    I("Rapsolja", OL, staple=True, aliases=("olja", "matolja", "neutral olja"), match="rapsolja -smörsmak -olivolja"),
    I("Sesamolja", OL, staple=True, aliases=("rostad sesamolja",)),
    I("Soja", OL, staple=True, aliases=("japansk soja", "sojasås", "tamari"), match="sojasås -sweet; japansk soja; soja -sojasås -bönor"),
    I("Sweet chilisås", OL, staple=True, aliases=("sweet chili",), match="sweet chili sauce; sweet chili sås; sweet chilisås"),
    I("Sriracha", OL, staple=True),
    I("Senap", OL, staple=True),
    I("Lönnsirap", OL, staple=True, aliases=("agavesirap", "sirap"), match="lönnsirap; agave sirap @skafferi/bakning"),
    I("Balsamvinäger", OL, staple=True),
    I("Vegansk majonnäs", OL, pkg="250 ml", aliases=("veganmajonnäs", "vegomajonnäs"), match="vegan mayo; vegansk majonnäs; vegomajonnäs"),
    I("Jordnötssmör", OL, pkg="350 g", match="jordnötssmör -granola; peanut butter @skafferi/bakning"),
    I("Tahini", OL, pkg="300 g"),
    I("Röd currypasta", OL, pkg="1 st", aliases=("currypasta", "thai röd currypasta"), match="red curry paste; röd currypasta; röd curry pasta @skafferi/asien"),
    # Nuts & seeds
    I("Jordnötter", NO, pkg="200 g", aliases=("salta jordnötter", "rostade jordnötter"), match="jordnötter -chilinötter"),
    I("Cashewnötter", NO, pkg="200 g", aliases=("cashew",)),
    I("Sesamfrön", NO, staple=True, aliases=("sesam",), match="sesam rostad; sesamfrö @skafferi"),
    I("Pumpafrön", NO, pkg="200 g", aliases=("pumpakärnor",), match="pumpafrön; pumpakärnor"),
    # Other
    I("Vatten", OV, shop=False, aliases=("kallt vatten", "kokande vatten", "varmt vatten")),
]


def IMG(url, credit, source):
    """An openly licensed photo (Wikimedia Commons). It is downloaded when seeding, like an
    imported recipe's image, so no image files live in the repository. The credit is shown
    on the recipe page, as the licences require."""
    return {"url": url, "credit": credit, "source": source}


def R(name, servings, minutes, ingredients, instructions, description="", image=None):
    return {
        "name": name, "servings": servings, "minutes": minutes,
        "ingredients": ingredients.strip(), "instructions": instructions.strip(),
        "description": description, "image": image,
    }


RECIPES = [
    R("Vegobullar med potatismos", 2, 30, """
500 g mjölig potatis
0,5 förp vegobullar
2 dl havredryck
50 g vegansk margarin
4 msk lingonsylt
Salt
""", """
Skala och koka potatisen mjuk i saltat vatten, ca 20 minuter.
Värm vegobullarna i lite margarin i en stekpanna.
Häll av potatisen, mosa med varm havredryck och margarin. Smaka av med salt.
Servera med vegobullar och lingonsylt.
""", "Husmanskost som alla gillar – klar på en halvtimme.", image=IMG(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/55/Plant_balls_served_with_mashed_potatoes%2C_peas%2C_cream_sauce_-_IKEA_Southampton_2025-12-29.jpg/1280px-Plant_balls_served_with_mashed_potatoes%2C_peas%2C_cream_sauce_-_IKEA_Southampton_2025-12-29.jpg",
        "Andy Li, CC0",
        "https://commons.wikimedia.org/wiki/File:Plant_balls_served_with_mashed_potatoes,_peas,_cream_sauce_-_IKEA_Southampton_2025-12-29.jpg",
    )),

    R("Chili sin carne", 4, 40, """
1 gul lök
2 klyftor vitlök
1 röd paprika
2 förp krossade tomater
1 förp kidneybönor
1 förp svarta bönor
2 msk tomatpuré
1 msk spiskummin
1 tsk rökt paprikapulver
1 tsk chiliflakes
1 grönsaksbuljong
1 msk rapsolja
3 dl basmatiris
""", """
Hacka lök, vitlök och paprika. Fräs i oljan några minuter.
Tillsätt kryddor och tomatpuré, fräs en minut till.
Häll i krossade tomater, sköljda bönor och buljong. Låt puttra 25 minuter.
Koka riset och servera.
""", "Mustig bönchili som blir godare dagen efter.", image=IMG(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/fa/Chilli_sine_carne_Zur_Tanne_Harsdorf.jpg/1280px-Chilli_sine_carne_Zur_Tanne_Harsdorf.jpg",
        "Benreis, CC BY-SA 4.0",
        "https://commons.wikimedia.org/wiki/File:Chilli_sine_carne_Zur_Tanne_Harsdorf.jpg",
    )),

    R("Röd linssoppa med kokos", 4, 35, """
1 gul lök
2 klyftor vitlök
20 g ingefära
2 morötter
3 dl röda linser
1 förp krossade tomater
1 förp kokosmjölk
8 dl vatten
1 grönsaksbuljong
2 tsk curry
1 tsk spiskummin
0,5 lime
Salt
""", """
Hacka lök, vitlök, ingefära och morötter. Fräs mjukt i en kastrull.
Tillsätt kryddor och fräs en minut.
Tillsätt linser, tomater, kokosmjölk, vatten och buljong. Koka 20 minuter.
Mixa slät, smaka av med limesaft och salt.
""", image=IMG(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4f/Red_lentil_soup_from_Turkey.jpg/1280px-Red_lentil_soup_from_Turkey.jpg",
        "E4024, CC BY-SA 4.0",
        "https://commons.wikimedia.org/wiki/File:Red_lentil_soup_from_Turkey.jpg",
    )),

    R("Kikärtscurry med spenat", 4, 30, """
1 gul lök
2 klyftor vitlök
20 g ingefära
2 förp kikärtor
1 förp kokosmjölk
1 förp krossade tomater
1 msk curry
1 tsk garam masala
1 tsk gurkmeja
1 förp babyspenat
3 dl basmatiris
0,5 kruka färsk koriander
1 msk rapsolja
""", """
Fräs hackad lök, vitlök och ingefära i oljan.
Tillsätt kryddorna och fräs en minut.
Tillsätt sköljda kikärtor, kokosmjölk och tomater. Sjud 15 minuter.
Vänd ner spenaten. Servera med ris och koriander.
""", image=IMG(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4f/Spinach-Chickpea_Curry_%283117324894%29.jpg/1280px-Spinach-Chickpea_Curry_%283117324894%29.jpg",
        "Kari Sullivan from Austin, TX, CC BY 2.0",
        "https://commons.wikimedia.org/wiki/File:Spinach-Chickpea_Curry_(3117324894).jpg",
    )),

    R("Falafel i pitabröd", 4, 20, """
1 förp falafel
4 pitabröd
1 förp hummus
1 gurka
2 tomater
0,5 rödlök
0,5 isbergssallad
1 dl vegansk majonnäs
""", """
Värm falafeln i ugnen enligt förpackningen.
Skär grönsakerna.
Värm pitabröden och fyll med hummus, sallad, grönsaker, falafel och majonnäs.
""", image=IMG(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/54/Falafel_in_a_pita.jpg/1280px-Falafel_in_a_pita.jpg",
        "Israel_photo_gallery, CC BY-SA 2.0",
        "https://commons.wikimedia.org/wiki/File:Falafel_in_a_pita.jpg",
    )),
]
