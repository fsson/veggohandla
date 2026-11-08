from decimal import Decimal

from django import template
from django.utils import translation
from django.utils.translation import gettext

from core.domain.units import format_number

register = template.Library()


def _swedish() -> bool:
    return (translation.get_language() or "sv").startswith("sv")


@register.filter
def kr(value):
    """12.9 -> '12,90 kr' (Swedish) or '12.90 SEK' (English)."""
    if value is None or value == "":
        return ""
    v = Decimal(value).quantize(Decimal("0.01"))
    whole, _, dec = f"{v:,.2f}".partition(".")
    if _swedish():
        return f"{whole.replace(',', ' ')},{dec} kr"
    return f"{whole}.{dec} SEK"


@register.filter
def kr_round(value):
    """412.3 -> '412 kr' (Swedish) or '412 SEK' (English), rounded to whole kronor."""
    if value is None:
        return ""
    whole = f"{int(Decimal(value).to_integral_value()):,}"
    return f"{whole.replace(',', ' ')} kr" if _swedish() else f"{whole} SEK"


@register.filter
def num(value):
    return format_number(Decimal(value)) if value is not None else ""


@register.filter
def initial(text):
    return (text or "?").strip()[:1].upper()


@register.filter
def hue(text):
    """Stable hue for image placeholders."""
    return sum(map(ord, text or "")) * 37 % 360


@register.filter
def product_url(product, retailer):
    return product.url(retailer or "willys")


@register.filter
def vegan_reason(code):
    """Translate the stored reason code of the vegan check (see domain/vegan.py)."""
    kind, _, arg = (code or "").partition(":")
    if kind == "contains":
        return gettext("Innehåller ”%(word)s”") % {"word": arg}
    return {
        "labelled": gettext("Märkt vegansk"),
        "no_animal": gettext("Inga animaliska ingredienser"),
        "produce": gettext("Frukt och grönt"),
        "no_list": gettext("Ingen ingredienslista"),
    }.get(kind, code or "")
