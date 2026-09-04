"""Price rule helpers: bulk tiers and simple markdowns."""

from typing import List, Tuple


class BulkTier:
    """A quantity threshold and the unit price that applies at/above it."""

    def __init__(self, min_qty: int, unit_price: float):
        self.min_qty = min_qty
        self.unit_price = unit_price


class TieredPricing:
    """Resolves the correct unit price for a quantity from tiers."""

    def __init__(self, tiers: List[BulkTier]):
        self.tiers = sorted(tiers, key=lambda t: t.min_qty)

    def unit_price_for(self, quantity: int, default_price: float) -> float:
        applicable = default_price
        for tier in self.tiers:
            if quantity >= tier.min_qty:
                applicable = tier.unit_price
        return applicable

    def price_line(self, quantity: int, default_price: float) -> float:
        price = self.unit_price_for(quantity, default_price)
        return round(price * quantity, 2)


def apply_markdown(price: float, markdown_pct: float) -> float:
    """Reduce a price by a percentage (0-100)."""
    if not (0 <= markdown_pct <= 100):
        raise ValueError("markdown_pct must be between 0 and 100")
    return round(price * (1 - markdown_pct / 100), 2)


def price_range(prices: List[float]) -> Tuple[float, float]:
    """Return (min, max) of a list of prices."""
    if not prices:
        raise ValueError("prices must not be empty")
    return (min(prices), max(prices))
