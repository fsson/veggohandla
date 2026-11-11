# Architecture

A personal, local app for planning vegan weekly meals and building a shopping list from a
local copy of the Willys/Hemköp product range. The goal is as little architecture as possible
with full functionality.

This document is written to be read top to bottom by someone learning Python and Django.
Part 1 explains the moving parts, part 2 follows one click through the code, part 3 says
where to start reading, and part 4 lists the design decisions that must not be broken.

---

## Part 1 – The big picture

The app is one Python process. It does two jobs:

1. **Serves web pages** to your browser (recipes, week planner, shopping list).
2. **Refreshes the product index** every morning in a background thread (it downloads
   products and prices from the stores into the local database).

Everything is stored in one file, `data/veggohandla.sqlite3`. There is no other server to install.

```
   Browser  ──HTTP──>  waitress (web server)
                           │
                           ▼
                        Django ── views.py ── services/ ── domain/
                           │                       │
                           ▼                       ▼
                    SQLite file  <──────  scheduler thread ── stores/axfood.py ──> Willys/Hemköp
```

### The stack, in one sentence each

| Part | What it is | Why |
|---|---|---|
| Django | Web framework: URLs, database models, forms, templates | One package gives us everything. |
| SQLite | A database in a single file | Nothing to install or run. Backup = copy `data/`. |
| htmx | A small JavaScript file (vendored) | Lets a click update part of a page without writing JavaScript. |
| SortableJS | Drag and drop (vendored) | Used in the week planner. |
| httpx | HTTP client | Downloads store data and imports recipes. |
| waitress + WhiteNoise | Production web server + static file server | Pure Python, runs on a Raspberry Pi. |
| pytest | Test runner | `uv run pytest` |
| ruff | Linter and formatter | `uv run ruff check --fix . && uv run ruff format .` |

No login and no user model: each person runs their own instance.

### Django vocabulary used in this repo

| Term | Meaning | Where |
|---|---|---|
| **Model** | A Python class that is a database table. Each attribute is a column. | `core/models.py` |
| **Migration** | A numbered script that changes the database to match the models. Created with `makemigrations`, applied with `migrate` (done automatically by `serve`). | `core/migrations/` |
| **View** | A function that takes a request and returns a response (a page). | `core/views.py` |
| **URL conf** | The table that maps a URL like `/recept/3/` to a view. | `core/urls.py` |
| **Template** | HTML with `{{ placeholders }}` and `{% logic %}`. | `core/templates/core/` |
| **Template filter** | A small function usable in templates, e.g. `{{ price|kr }}`. | `core/templatetags/vl.py` |
| **Management command** | A script run as `uv run manage.py <name>`. | `core/management/commands/` |
| **Settings** | Configuration (database path, debug on/off). | `config/settings.py` |

### The three layers of our own code

We keep the code in three layers so each part is easy to understand and test alone:

| Layer | Folder | Rule |
|---|---|---|
| **Domain** | `core/domain/` | Pure Python functions. No Django, no database, no network. Input in, answer out. This is the hard logic (units, parsing, merging amounts, vegan check) and it has the most tests. |
| **Services** | `core/services/` | Glue: read and write the database using the models, call domain functions. |
| **Views** | `core/views.py` | Thin. Read the request, call a service, pick a template. No business logic. |

The only code that talks to the internet is `core/stores/axfood.py`, and it is only called
from `services/index.py`. If the stores are down the app keeps working on what it has stored.

### Folder map

```
config/              Django project settings, root URLs, wsgi entry point
core/                The one Django app – everything of ours lives here
  models.py            All database tables
  views.py             All pages
  urls.py              URL -> view table
  forms.py             Recipe form
  admin.py             Django's built-in admin, for exceptional manual edits
  seed_data.py         Starting data: sections, ingredients (with product matching), 5 recipes
  domain/              Pure logic
    units.py             Units, conversion between them, number formatting
    parse.py             "1 ½ dl havredryck, kall" -> (1.5, dl, havredryck, kall)
    aggregate.py         Scale recipes and merge amounts into shopping rows
    vegan.py             Strict vegan check of an ingredient list
  services/            Database-aware logic
    catalog.py           Ingredient -> matching products -> cheapest for the amount
    shopping.py          Builds the shopping list; recipe cost
    recipes.py           Ingredient text -> recipe lines
    ingredients.py       The ingredient page: preview/save match rules, aliases, merge
    importer.py          Import a recipe from a web page (schema.org JSON-LD)
    images.py            Shrink uploaded/imported recipe images
    index.py             Builds the local product index
    scheduler.py         Background thread that starts an index run each morning
  stores/axfood.py     The only code that talks to Willys/Hemköp
  management/commands/
    serve.py             Start everything: migrate, seed, scheduler, web server
    index.py             Run the product index by hand
    seed.py              Insert seed data (safe to run repeatedly)
  templates/ static/   HTML, CSS, vendored htmx/SortableJS
  tests/               pytest tests
deploy/install.sh    Installs the app as a systemd service (e.g. Raspberry Pi)
data/                Your database and uploaded images (not in git)
```

---

## Part 2 – Following one click through the code

Example: you open the shopping list for this week (`/handla/`).

1. The browser sends `GET /handla/` to waitress, which hands it to Django.
2. `config/urls.py` forwards to `core/urls.py`, which maps `handla/` to
   `views.shopping_list`.
3. `shopping_list` calls `shopping.build(week, retailer)` in `services/shopping.py`.
4. `build` reads the week's `PlannedMeal` rows from the database, and for each recipe line
   makes a `Line(ingredient, quantity, unit)`.
5. It passes those lines to `domain/aggregate.py`, which scales them to the planned servings and
   merges "2 dl havredryck" + "3 dl havredryck" into "5 dl havredryck". This function knows
   nothing about Django; it is just maths on `Decimal` numbers.
6. For each merged ingredient, `services/catalog.py` finds the matching products (using the
   ingredient's `match` rule), works out how many packages are needed, and picks the cheapest.
7. The result is a `ShoppingList` object. The view renders `templates/core/shopping.html`
   with it and returns the HTML.
8. When you click a button on a row (say, to choose another product), htmx sends a small
   request to e.g. `shopping_choose`, and the server returns only that row's HTML
   (`partials/shopping_row.html`), which htmx swaps into the page. No page reload, and no
   JavaScript of our own.

The same pattern repeats everywhere: URL -> view -> service -> domain, then a template. When
you want to understand a feature, find its URL in `urls.py` and follow it down.

### The morning refresh

`manage.py serve` starts `services/scheduler.py` in a thread. Once a minute it asks "is it
inside the stores' allowed time window, and is there work to do?". If yes it calls
`services/index.py`, which uses `stores/axfood.py` to download categories, products and
prices (one request every 10 seconds, as the stores' robots.txt asks), runs the vegan check
(`domain/vegan.py`) and saves `Product` and `Price` rows. Only products that pass the vegan
check are ever shown.

---

## Part 3 – Where to start reading

1. `core/models.py` – the data. Read the data model below alongside it.
2. `core/urls.py` – the list of everything the app can do.
3. `core/domain/parse.py` and its tests in `core/tests/test_domain.py` – the easiest real
   logic: text in, numbers out. Tests show how each function is meant to be used.
4. `core/domain/aggregate.py` – merging amounts.
5. `core/services/shopping.py` – how the pieces combine into the shopping list.
6. `core/views.py` and the templates – how it reaches the screen.
7. `stores/axfood.py` and `services/index.py` last; they are the most intricate.

Everyday commands are in `README.md`.

---

## Part 4 – Data model and design decisions

### Data model

```
Category ─< Ingredient ─< IngredientAlias            (names that also match, optional implied unit)
  (store categories)  │  match: rule for which products are the ingredient
                      │  preferred_code: the user's chosen product (otherwise cheapest)
                      │
                      ├─< RecipeIngredient >─ Recipe ─< PlannedMeal (date, servings)
                      └─< ShoppingItemState (week: already at home)

Product (article code, name, size, category, ingredients, vegan?) ─< Price (chain, price, promotion)
ExtraItem (week: product from the index + count)    AppSettings (chain, last servings, index status)
```

### Design decisions

1. **Three levels: recipe line → ingredient → product.** A recipe says "vegobullar", not a
   brand. An ingredient is a group ("what it is") of products in the index; which one is
   bought is decided in the shopping list. Recipes therefore never break when a product is
   discontinued or changes price, and the cheapest alternative is picked every week.
2. **The group is decided by an explicit rule, never by similarity.** `Ingredient.match` is
   words that must appear at the start of words in the product name, `-word` to exclude,
   `;` for alternatives and `@category` for a store category (otherwise the section's
   categories). The rules live in the seed data and are checked against real names. Merging
   in the shopping list only happens on ingredient id.
3. **The default choice is the cheapest for the amount needed.** Whole packages
   (`packages_needed`), loose weight per kg, promotion price only from the promotion's
   minimum quantity. On equal price the least waste wins, then the shortest name (the
   "plain" variant). A manual choice (`preferred_code`) applies until it is reset.
4. **The shopping list is not stored – it is computed.** Only the user's changes are stored
   ("already at home", extra products, chosen products). No ticking off – the app is used
   at the computer.
5. **Weeks are date ranges**, no table of their own.
6. **Units have dimensions** (mass, volume, st, förp, klyfta …). Between dimensions only
   with ingredient knowledge (grams per piece, grams per dl, package size). A product that
   weighs about one piece counts as one piece (an avocado of 147 g = 1 avocado).
7. **"förp" in a recipe = the ingredient's standard package.** The product's size only
   affects how many packages are bought. Two costs: *consumed* (per recipe) and
   *purchase* (whole packages, in the shopping list).
8. **The index is Willys' range; Hemköp supplies prices for the same article codes.** The
   chains are owned by Axfood and share article codes, so the same product is compared
   without name matching. Products sold per piece at one chain and per kg at the other
   are not compared.
9. **The vegan check is strict** (`domain/vegan.py`). Labelled vegan or an ingredient list
   without animal words → included. An animal word → never included. No ingredient list →
   only unprocessed fruit and vegetables. Trace warnings are ignored. The ingredient list
   is stored, so a changed rule can be re-run locally (`index --reclassify`). The app is
   about food only: every food category is crawled, including meat and fish so vegan
   products filed there are found, and the non-food departments (`NON_FOOD_TOP_CATEGORIES`)
   never are, except food subcategories inside them (`FOOD_IN_NON_FOOD`: Hälsokost). In meat and fish (`LABEL_ONLY_CATEGORIES`) only the chain's "Vegan" label
   counts. The first full vetting takes more mornings; products matching an ingredient go first.
10. **The store integration is decoupled and follows the chains' rules.** Network requests
    only happen while indexing. The chains' robots.txt is followed: `Crawl-delay: 10` (one
    request per 10 s per chain) and `Visit-time: 0400-0845` (UTC); no requests are made
    outside the window, and a running index pauses and continues next time. An
    ingredient list is fetched once per product, those matching an ingredient first.
    Errors only abort the indexing. The pace is fixed in code and not configurable.
11. **Product matching and aliases can be edited in the app, with a preview.** The
    ingredient page (`services/ingredients.py`) shows which vegan products a rule matches,
    cheapest first, and which ones a `-word` keeps out, before anything is saved. A saved
    rule sets `match_edited`, so `seed` no longer overwrites it; "Återställ standard" goes back
    to the seed rule. Aliases must be unique across all ingredient names and aliases (exact
    matching), and apply to recipe text entered from then on. A duplicate created from
    recipe text ("gulcurry" next to "Curry") is fixed by merging: its recipe lines and
    aliases move to the other ingredient and its name becomes an alias there, so neither
    new recipe text nor `seed` recreates it. Only unused ingredients can be deleted. The section, staple and
    "in shopping list" flags can be changed on the page too (seed never changes an existing
    ingredient). Conversion facts
    still come from the seed data. New ingredients from recipe text get a guessed section,
    from where the index's products with the same name are (`guess_category`, Övrigt when
    nothing matches). Django admin exists for
    exceptional cases.
12. **Personal use only.** Willys' terms allow use of the content "endast för ditt
    personliga bruk" (only for your personal use). Therefore each person runs their own
    local instance with their own index; the app must not be operated as a shared or public
    service.
13. **The interface is Swedish only.** There is no translation layer: texts are written
    directly in templates and code, numbers use a decimal comma and prices render as
    `12,90 kr` (template filters in `templatetags/vl.py`). Anyone who needs another language
    can use the browser's built-in translator. Consequences that matter:
    - Text stored in the database (index progress, section names) is plain Swedish.
    - `USE_I18N` stays on only so Django's own Swedish month/weekday names and form
      messages are used; `LANGUAGE_CODE = "sv"` and there is no locale middleware.
    - The recipe parser accepts both `1,5` and `1.5`, so imported recipe text still parses.

14. **Hosting is one process: `manage.py serve`.** It applies migrations, seeds an empty
    database, starts the scheduler thread and serves the app with waitress. No cron, no
    separate worker, no reverse proxy and no collectstatic step: static files come from
    WhiteNoise (straight from the app directories), recipe images from a Django view. The
    defaults are production-safe (DEBUG off, logs to stdout); development opts in with
    `VEGGOHANDLA_DEBUG=1`. `deploy/install.sh` turns that into a systemd service, so hosting
    on a Raspberry Pi is: clone, run the script.
    - The scheduler checks once a minute: inside the visiting hours, no run in progress, and
      work to do (today's prices not fetched, or products left to vet). After a failure it
      backs off for 30 minutes.
    - Prices are "fresh" for the calendar day (UTC), not for N hours, so every morning gets
      a price refresh regardless of when yesterday's run finished.
    - Only one run at a time, also across processes: a run claims the index atomically in
      the database and writes a heartbeat for every request; a run silent for 10 minutes
      counts as dead.
    - The crawler fetches a category's pages before opening a transaction, so the 10 s waits
      never hold SQLite's write lock and the app stays usable during the morning refresh.
    - The app has no login, so it is meant for a home network, reached from outside through
      a VPN on the Pi (PiVPN/WireGuard) – never exposed to the internet (also because of the
      personal-use terms).

---

## Extending

- **More chains:** write an adapter with `category_tree`/`list_category`/`fetch_details`
  and add the chain to `Retailer` and `index.py`. Without shared article codes, EAN is
  needed to compare the same product.
- **Price history:** add a `PriceObservation` table filled on every indexing run.
- **Pantry:** "already at home" exists per week; a real inventory would be its own model
  deducted in `services/shopping.build`.
