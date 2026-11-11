from decimal import Decimal

from django import template

from core.domain.units import format_number

register = template.Library()


@register.filter
def kr(value):
    """12.9 -> '12,90 kr'."""
    if value is None or value == "":
        return ""
    v = Decimal(value).quantize(Decimal("0.01"))
    whole, _, dec = f"{v:,.2f}".partition(".")
    return f"{whole.replace(',', ' ')},{dec} kr"


@register.filter
def kr_round(value):
    """412.3 -> '412 kr', rounded to whole kronor."""
    if value is None:
        return ""
    whole = f"{int(Decimal(value).to_integral_value()):,}"
    return f"{whole.replace(',', ' ')} kr"


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
        return f"Innehåller ”{arg}”"
    return {
        "labelled": "Märkt vegansk",
        "no_animal": "Inga animaliska ingredienser",
        "produce": "Frukt och grönt",
        "no_list": "Ingen ingredienslista",
        "label_required": "Kräver veganmärkning",
    }.get(kind, code or "")
