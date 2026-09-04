"""Order assembly and totals."""

from .discounts import DiscountRule
from .tax import TaxTable


class Order:
    """A collection of line items with discount and tax handling."""

    def __init__(self, tax_table: TaxTable = None):
        self.lines = []
        self.tax_table = tax_table or TaxTable()

    def add_line(self, line_item) -> None:
        self.lines.append(line_item)

    def subtotal(self) -> float:
        return round(sum(line.subtotal() for line in self.lines), 2)

    def tax_total(self) -> float:
        total = 0.0
        for line in self.lines:
            total += self.tax_table.tax_for(line.item.category, line.subtotal())
        return round(total, 2)

    def total(self, discount_rule: DiscountRule = None) -> float:
        subtotal = self.subtotal()
        discounted = discount_rule.apply(subtotal) if discount_rule else subtotal
        discount_ratio = discounted / subtotal if subtotal else 1.0
        tax = round(self.tax_total() * discount_ratio, 2)
        return round(discounted + tax, 2)

    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    def summary(self) -> dict:
        return {
            "subtotal": self.subtotal(),
            "tax": self.tax_total(),
            "item_count": self.item_count(),
            "line_count": len(self.lines),
        }
