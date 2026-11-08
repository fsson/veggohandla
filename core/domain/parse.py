"""Parse ingredient lines such as '500 g mjölig potatis' or '1 gul lök, finhackad'."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .units import lookup_unit

_UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅛": "1/8",
}

_NUM = r"\d+(?:[.,]\d+)?"
# "1 1/2", "1/2", "1,5", "2-3", "2–3"
_QTY_RE = re.compile(
    rf"^\s*(?:ca\.?\s+|cirka\s+)?"
    rf"(?P<q>(?:\d+\s+)?\d+/\d+|{_NUM}(?:\s*[-–]\s*{_NUM})?)"
    rf"\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedLine:
    quantity: Decimal | None
    unit: str  # unit code, "" if none
    name: str
    note: str = ""


def _to_decimal(text: str) -> Decimal:
    text = text.strip().replace(",", ".")
    if re.search(r"[-–]", text):  # range: take the upper value
        text = re.split(r"\s*[-–]\s*", text)[-1]
    if "/" in text:
        parts = text.split()
        whole = Decimal(parts[0]) if len(parts) == 2 else Decimal(0)
        num, den = parts[-1].split("/")
        return whole + Decimal(num) / Decimal(den)
    return Decimal(text)


def _normalize_fractions(text: str) -> str:
    for sym, frac in _UNICODE_FRACTIONS.items():
        # "1½" -> "1 1/2", "½" -> "1/2"
        text = re.sub(rf"(\d){sym}", rf"\1 {frac}", text)
        text = text.replace(sym, frac)
    return text


def parse_line(line: str) -> ParsedLine | None:
    """Parse a line. Returns None for empty lines."""
    text = _normalize_fractions(line.strip().lstrip("-•*").strip())
    if not text:
        return None

    note = ""
    # Note in parentheses or after a comma
    m = re.search(r"\(([^)]*)\)", text)
    if m:
        note = m.group(1).strip()
        text = (text[: m.start()] + text[m.end():]).strip()
    if "," in text:
        # A comma can be a decimal separator ("1,5 dl") – only split on a comma followed by a space
        head, sep, tail = text.partition(", ")
        if sep:
            text, note = head.strip(), ", ".join(x for x in (tail.strip(), note) if x)

    quantity: Decimal | None = None
    unit = ""
    rest = text
    m = _QTY_RE.match(text)
    if m:
        try:
            quantity = _to_decimal(m.group("q"))
            rest = m.group("rest")
        except (InvalidOperation, ValueError, ZeroDivisionError):
            quantity = None
            rest = text
    if quantity is not None:
        first, _, remainder = rest.partition(" ")
        u = lookup_unit(first)
        if u is not None:
            unit = u.code
            rest = remainder
        else:
            unit = "st"
    name = re.sub(r"\s+", " ", rest).strip(" .")
    if not name:
        return None
    return ParsedLine(quantity=quantity, unit=unit if quantity is not None else "", name=name, note=note)


def normalize_name(name: str) -> str:
    """Key for exact name matching (lowercase, single spaces)."""
    return re.sub(r"\s+", " ", name.strip().lower())
