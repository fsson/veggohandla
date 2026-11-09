"""Units of measure and conversion.

Pure domain logic with no Django dependencies.

Every unit belongs to a *dimension*. Within a dimension, units convert with a fixed
factor to the dimension's base unit (g, ml). Between dimensions, ingredient knowledge
is required (e.g. 1 st gul lök ≈ 110 g), see `IngredientFacts`.

Countable units that can't be converted into each other (st, klyfta, knippe …) are
each their own dimension. "förp" is its own dimension that can be converted via the
ingredient's package size.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

MASS = "mass"
VOLUME = "volume"
PACKAGE = "förp"
PIECE = "st"


@dataclass(frozen=True)
class Unit:
    code: str
    dimension: str
    factor: Decimal  # number of base units per unit
    aliases: tuple[str, ...] = ()
    plural: str = ""


_UNITS: list[Unit] = [
    Unit("g", MASS, Decimal(1), ("gram",)),
    Unit("hg", MASS, Decimal(100), ("hekto",)),
    Unit("kg", MASS, Decimal(1000), ("kilo",)),
    Unit("krm", VOLUME, Decimal(1), ("kryddmått",)),
    Unit("ml", VOLUME, Decimal(1), ("milliliter",)),
    Unit("tsk", VOLUME, Decimal(5), ("tesked", "teskedar")),
    Unit("msk", VOLUME, Decimal(15), ("matsked", "matskedar")),
    Unit("cl", VOLUME, Decimal(10), ()),
    Unit("dl", VOLUME, Decimal(100), ("deciliter",)),
    Unit("l", VOLUME, Decimal(1000), ("liter", "lit")),
    Unit("st", PIECE, Decimal(1), ("styck", "stycken", "stk")),
    Unit(
        "förp",
        PACKAGE,
        Decimal(1),
        (
            "förpackning",
            "förpackningar",
            "paket",
            "pkt",
            "burk",
            "burkar",
            "påse",
            "påsar",
            "ask",
            "askar",
            "tetra",
            "frp",
        ),
    ),
    Unit("klyfta", "klyfta", Decimal(1), ("klyftor",), "klyftor"),
    Unit("knippe", "knippe", Decimal(1), ("knippen", "knippa"), "knippen"),
    Unit("kruka", "kruka", Decimal(1), ("krukor",), "krukor"),
    Unit("nypa", "nypa", Decimal(1), ("nypor",), "nypor"),
    Unit("skiva", "skiva", Decimal(1), ("skivor",), "skivor"),
]

UNITS: dict[str, Unit] = {u.code: u for u in _UNITS}
_LOOKUP: dict[str, Unit] = {}
for _u in _UNITS:
    _LOOKUP[_u.code] = _u
    for _a in _u.aliases:
        _LOOKUP[_a] = _u


def lookup_unit(token: str) -> Unit | None:
    """Find a unit from text, e.g. 'Msk', 'dl.', 'burkar'."""
    return _LOOKUP.get(token.strip().rstrip(".").lower())


def dimension_of(unit_code: str) -> str:
    """Dimension for a unit code. An empty unit means 'st'."""
    if not unit_code:
        return PIECE
    unit = UNITS.get(unit_code)
    return unit.dimension if unit else unit_code


def to_base(amount: Decimal, unit_code: str) -> tuple[Decimal, str]:
    """Convert to the dimension's base unit. Returns (amount, dimension)."""
    if not unit_code:
        return amount, PIECE
    unit = UNITS.get(unit_code)
    if unit is None:
        # Unknown unit: its own dimension, no conversion.
        return amount, unit_code
    return amount * unit.factor, unit.dimension


@dataclass(frozen=True)
class IngredientFacts:
    """Ingredient knowledge that makes conversion between dimensions possible."""

    grams_per_piece: Decimal | None = None
    grams_per_dl: Decimal | None = None
    # The recipe's "förp" (the ingredient's standard package), in base units
    package_amount: Decimal | None = None
    package_dimension: str | None = None  # MASS, VOLUME or PIECE
    # The package actually bought (the chosen product). Only affects how many to buy.
    purchase_amount: Decimal | None = None
    purchase_dimension: str | None = None

    def buy_unit(self) -> tuple[Decimal, str] | None:
        if self.purchase_amount and self.purchase_dimension:
            return self.purchase_amount, self.purchase_dimension
        if self.package_amount and self.package_dimension:
            return self.package_amount, self.package_dimension
        return None

    def edges(self) -> dict[tuple[str, str], Decimal]:
        """Edges of the conversion graph: (from, to) -> factor (base units)."""
        e: dict[tuple[str, str], Decimal] = {}

        def add(a: str, b: str, f: Decimal) -> None:
            if f and f > 0:
                e[(a, b)] = f
                e[(b, a)] = 1 / f

        if self.grams_per_piece:
            add(PIECE, MASS, self.grams_per_piece)
        if self.grams_per_dl:
            add(VOLUME, MASS, self.grams_per_dl / 100)
        if self.package_amount and self.package_dimension:
            add(PACKAGE, self.package_dimension, self.package_amount)
        return e


def conversion_factor(src: str, dst: str, facts: IngredientFacts) -> Decimal | None:
    """Factor that converts a base amount in `src` to a base amount in `dst` (BFS)."""
    if src == dst:
        return Decimal(1)
    edges = facts.edges()
    frontier: list[tuple[str, Decimal]] = [(src, Decimal(1))]
    seen = {src}
    while frontier:
        nxt: list[tuple[str, Decimal]] = []
        for node, f in frontier:
            for (a, b), k in edges.items():
                if a == node and b not in seen:
                    if b == dst:
                        return f * k
                    seen.add(b)
                    nxt.append((b, f * k))
        frontier = nxt
    return None


def packages_needed(amount: Decimal, package_amount: Decimal) -> int:
    """Number of whole packages needed to cover the amount."""
    if package_amount <= 0:
        raise ValueError("Förpackningsstorlek måste vara positiv")
    # Small tolerance so that 3 × 0.333… doesn't become 2 packages.
    ratio = (amount / package_amount).quantize(Decimal("0.001"))
    return max(1, int(ratio.to_integral_value(rounding=ROUND_CEILING))) if amount > 0 else 0


# ---------------------------------------------------------------- formatting


def format_number(value: Decimal, max_decimals: int = 2) -> str:
    """Format a number without unnecessary zeros: 1,5 · 0,25 · 2 (decimal comma)."""
    q = Decimal(1).scaleb(-max_decimals)
    v = value.quantize(q).normalize()
    if v == v.to_integral():
        v = v.quantize(Decimal(1))
    text = format(v, "f")
    return text.replace(".", ",")


def best_display(amount: Decimal, dimension: str, prefer_unit: str | None = None) -> tuple[Decimal, str]:
    """Pick a readable unit for a base amount.

    If `prefer_unit` is given (e.g. all lines used 'dl') it is used.
    """
    if prefer_unit and prefer_unit in UNITS and UNITS[prefer_unit].dimension == dimension:
        # Keep the recipe's unit, but step up to kg/l once the amount reaches a whole one.
        big = {MASS: "kg", VOLUME: "l"}.get(dimension)
        if not (big and amount >= UNITS[big].factor and UNITS[prefer_unit].factor < UNITS[big].factor):
            return amount / UNITS[prefer_unit].factor, prefer_unit
    if dimension == MASS:
        return (amount / 1000, "kg") if amount >= 1000 else (amount, "g")
    if dimension == VOLUME:
        if amount >= 1000:
            return amount / 1000, "l"
        if amount >= 100:
            return amount / 100, "dl"
        if amount >= 15 and amount % 15 == 0:
            return amount / 15, "msk"
        if amount >= 5 and amount % 5 == 0:
            return amount / 5, "tsk"
        return amount, "ml"
    return amount, dimension


def format_quantity(amount: Decimal, dimension: str, prefer_unit: str | None = None) -> str:
    value, unit = best_display(amount, dimension, prefer_unit)
    u = UNITS.get(unit)
    if u and u.plural and value > 1:
        unit = u.plural
    return f"{format_number(value)} {unit}".strip()
