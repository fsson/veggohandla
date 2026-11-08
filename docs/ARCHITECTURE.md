# Architecture

A personal, local app. The goal is as little architecture as possible with full functionality.

## Stack

| Part | Choice | Why |
|---|---|---|
| Web | Django 5.2 (LTS) | ORM, migrations, forms, admin – all in one. |
| Interactivity | htmx + SortableJS (vendored) | Server-rendered, no build step, no Node. |
| Database | SQLite in `data/` (WAL) | One file. Nothing to install. |
| Styling | Hand-written CSS (`core/static/core/app.css`) | Light theme, desktop first, no dependencies. |
| HTTP | httpx | Store data and recipe import. |
| Serving | waitress + WhiteNoise | Production WSGI server and static files, both pure Python (run anywhere, incl. a Raspberry Pi). |

No login and no household/user model: each person runs their own instance.

## Code

```
core/
  domain/            Pure logic without Django – the hard part, and the tests
    units.py         Units, dimensions, conversion, formatting
    parse.py         "1 ½ dl havredryck, kall" -> (1.5, dl, havredryck, kall)
    aggregate.py     Scaling and merging into shopping rows
    vegan.py         Strict vegan check of an ingredient list
  stores/axfood.py   Willys/Hemköp adapter (the only code that talks to the stores)
  services/
    index.py         Builds the local index (categories -> products, prices, vegan check)
    scheduler.py     Starts an index run every morning (inside `manage.py serve`)
    catalog.py       Ingredient -> matching products -> cheapest for the amount
    shopping.py      The shopping list and recipe cost
    recipes.py       Ingredient text -> recipe lines, section for new ingredients
    importer.py      Recipe import (schema.org JSON-LD)
  management/commands/
    serve.py         Hosting entry point: migrate, seed, scheduler, waitress
    index.py         One index run by hand (`manage.py index`)
    seed.py          Seed data (idempotent)
  views.py           Thin views, return whole pages or htmx fragments
  seed_data.py       Sections, ingredients with product matching, recipes as text
deploy/install.sh    Installs/updates the app as a systemd service (e.g. on a Raspberry Pi)
```

Language: the app is for Swedish users and Swedish stores. The interface, the seed data
(ingredient and recipe names) and the product names are Swedish (see decision 13). The
README is English. Code, comments and these docs are English.

## Data model

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

### Decisions

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
   is stored, so a changed rule can be re-run locally (`index --reclassify`). Everything
   is crawled except the top categories for meat, fish and non-food (`SKIPPED_TOP_WORDS`),
   so vegan products in dairy, frozen, drinks and so on are found; the first full vetting
   takes more mornings, products matching an ingredient go first.
10. **The store integration is decoupled and follows the chains' rules.** Network requests
    only happen while indexing. The chains' robots.txt is followed: `Crawl-delay: 10` (one
    request per 10 s per chain) and `Visit-time: 0400-0845` (UTC); no requests are made
    outside the window, and a running index pauses and continues next time. An
    ingredient list is fetched once per product, those matching an ingredient first.
    Errors only abort the indexing. The pace is fixed in code and not configurable.
11. **Nothing in the app edits ingredients.** Section, conversion facts and product
    matching come from the seed data; new ingredients from recipe text get a section
    according to where the index's products with the same name are. Django admin exists
    for exceptional cases.
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

## Extending

- **More chains:** write an adapter with `category_tree`/`list_category`/`fetch_details`
  and add the chain to `Retailer` and `index.py`. Without shared article codes, EAN is
  needed to compare the same product.
- **Price history:** add a `PriceObservation` table filled on every indexing run.
- **Pantry:** "already at home" exists per week; a real inventory would be its own model
  deducted in `services/shopping.build`.
- **Edit product matching in the app:** a field for `Ingredient.match` with a preview of
  the matching products (`catalog.candidates`).
