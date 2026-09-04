"""Order-level discount rules."""


class DiscountRule:
    """Base class for a discount applied to an order subtotal."""

    def apply(self, subtotal: float) -> float:
        raise NotImplementedError


class PercentDiscount(DiscountRule):
    def __init__(self, percent: float):
        if not (0 <= percent <= 100):
            raise ValueError("percent must be between 0 and 100")
        self.percent = percent

    def apply(self, subtotal: float) -> float:
        return round(subtotal * (1 - self.percent / 100), 2)


class FlatDiscount(DiscountRule):
    def __init__(self, amount: float):
        if amount < 0:
            raise ValueError("amount must not be negative")
        self.amount = amount

    def apply(self, subtotal: float) -> float:
        result = subtotal - self.amount
        return round(max(result, 0.0), 2)


class ThresholdDiscount(DiscountRule):
    """A percent discount that only applies above a minimum subtotal."""

    def __init__(self, min_subtotal: float, percent: float):
        self.min_subtotal = min_subtotal
        self.percent = percent

    def apply(self, subtotal: float) -> float:
        if subtotal < self.min_subtotal:
            return round(subtotal, 2)
        return round(subtotal * (1 - self.percent / 100), 2)


def best_discount(subtotal: float, rules) -> float:
    """Apply every rule and return the lowest resulting total."""
    if not rules:
        return round(subtotal, 2)
    results = [rule.apply(subtotal) for rule in rules]
    return min(results)
