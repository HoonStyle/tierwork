"""Tax calculation helpers."""

DEFAULT_TAX_RATE = 0.08


class TaxTable:
    """Per-category tax rates with a fallback default rate."""

    def __init__(self, rates=None, default_rate: float = DEFAULT_TAX_RATE):
        self.rates = dict(rates or {})
        self.default_rate = default_rate

    def rate_for(self, category: str) -> float:
        return self.rates.get(category, self.default_rate)

    def tax_for(self, category: str, amount: float) -> float:
        rate = self.rate_for(category)
        return round(amount * rate, 2)


def total_with_tax(amount: float, rate: float) -> float:
    return round(amount * (1 + rate), 2)
