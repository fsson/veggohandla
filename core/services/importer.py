"""Import recipes from a web page via schema.org/Recipe (JSON-LD).

Most Swedish recipe sites publish the recipe as structured data, so we need no
site-specific scraping.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field

import httpx
from django.utils.translation import gettext

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Veggohandla/0.2"
_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)


class ImportError_(Exception):
    pass


@dataclass
class ImportedRecipe:
    name: str
    description: str = ""
    servings: int = 4
    minutes: int | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: str = ""
    image_url: str = ""
    source_url: str = ""


def _find_recipe(node):
    if isinstance(node, list):
        for n in node:
            if (r := _find_recipe(n)) is not None:
                return r
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
            return node
        for key in ("@graph", "mainEntity"):
            if key in node and (r := _find_recipe(node[key])) is not None:
                return r
    return None


def _text(value) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def _instructions(value) -> str:
    steps: list[str] = []

    def walk(v):
        if isinstance(v, str):
            steps.extend(s.strip() for s in _text(v).splitlines() if s.strip())
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            if "itemListElement" in v:
                walk(v["itemListElement"])
            elif "text" in v:
                walk(v["text"])

    walk(value)
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def _duration_minutes(value) -> int | None:
    m = re.fullmatch(r"P(?:T)?(?:(\d+)H)?(?:(\d+)M)?", str(value or ""))
    if not m or not any(m.groups()):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _image(value) -> str:
    if isinstance(value, list) and value:
        return _image(value[0])
    if isinstance(value, dict):
        return value.get("url", "")
    return str(value or "")


def parse_html(page: str, url: str = "") -> ImportedRecipe:
    for block in _LD_RE.findall(page):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        r = _find_recipe(data)
        if r is None:
            continue
        servings = 4
        yld = r.get("recipeYield")
        if isinstance(yld, list):
            yld = yld[0] if yld else ""
        if m := re.search(r"\d+", str(yld or "")):
            servings = max(1, min(int(m.group()), 50))
        return ImportedRecipe(
            name=_text(r.get("name")) or gettext("Importerat recept"),
            description=_text(r.get("description"))[:500],
            servings=servings,
            minutes=_duration_minutes(r.get("totalTime") or r.get("cookTime")),
            ingredients=[_text(i) for i in r.get("recipeIngredient") or [] if _text(i)],
            instructions=_instructions(r.get("recipeInstructions")),
            image_url=_image(r.get("image")),
            source_url=url,
        )
    raise ImportError_(gettext("Hittade inget recept på sidan (saknar schema.org/Recipe)."))


def fetch(url: str) -> ImportedRecipe:
    if not re.match(r"^https?://", url):
        raise ImportError_(gettext("Ange en webbadress som börjar med http:// eller https://"))
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ImportError_(gettext("Kunde inte hämta sidan: %(error)s") % {"error": e}) from e
    return parse_html(r.text, url)


def download_image(url: str, max_bytes: int = 8 * 1024 * 1024) -> bytes | None:
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    if not r.headers.get("content-type", "").startswith("image/") or len(r.content) > max_bytes:
        return None
    return r.content
