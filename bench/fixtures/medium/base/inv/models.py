"""Core data models for the inventory calculator."""

from dataclasses import dataclass, field


@dataclass
class Item:
    """A single catalog item."""

    sku: str
    name: str
    category: str
    unit_price: float

    def __post_init__(self):
        if self.unit_price < 0:
            raise ValueError("unit_price must not be negative")


@dataclass
class LineItem:
    """One line in an order: an item plus a quantity."""

    item: Item
    quantity: int

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

    def subtotal(self) -> float:
        return round(self.item.unit_price * self.quantity, 2)


@dataclass
class Catalog:
    """A simple lookup of items by SKU."""

    items: dict = field(default_factory=dict)

    def add(self, item: Item) -> None:
        self.items[item.sku] = item

    def get(self, sku: str) -> Item:
        if sku not in self.items:
            raise KeyError(f"unknown sku: {sku}")
        return self.items[sku]

    def all_items(self):
        return list(self.items.values())
