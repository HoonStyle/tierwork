import os
import tempfile
import unittest

from inv.models import Catalog, Item, LineItem
from inv.pricing import BulkTier, TieredPricing, apply_markdown, price_range
from inv.discounts import (
    PercentDiscount,
    FlatDiscount,
    ThresholdDiscount,
    best_discount,
)
from inv.tax import TaxTable, total_with_tax
from inv.order import Order
from inv.io_csv import (
    export_catalog,
    import_catalog,
    import_order_lines,
    export_order_lines,
)


class ModelsTest(unittest.TestCase):
    def test_item_rejects_negative_price(self):
        with self.assertRaises(ValueError):
            Item(sku="a", name="A", category="misc", unit_price=-1)

    def test_line_item_subtotal(self):
        item = Item(sku="a", name="A", category="misc", unit_price=2.5)
        line = LineItem(item=item, quantity=4)
        self.assertEqual(line.subtotal(), 10.0)

    def test_line_item_rejects_nonpositive_quantity(self):
        item = Item(sku="a", name="A", category="misc", unit_price=2.5)
        with self.assertRaises(ValueError):
            LineItem(item=item, quantity=0)

    def test_catalog_add_and_get(self):
        catalog = Catalog()
        item = Item(sku="a", name="A", category="misc", unit_price=1.0)
        catalog.add(item)
        self.assertIs(catalog.get("a"), item)

    def test_catalog_get_missing_raises(self):
        catalog = Catalog()
        with self.assertRaises(KeyError):
            catalog.get("missing")

    def test_catalog_all_items(self):
        catalog = Catalog()
        catalog.add(Item(sku="a", name="A", category="misc", unit_price=1.0))
        catalog.add(Item(sku="b", name="B", category="misc", unit_price=2.0))
        self.assertEqual(len(catalog.all_items()), 2)


class PricingTest(unittest.TestCase):
    def test_tiered_pricing_below_all_tiers(self):
        tp = TieredPricing([BulkTier(10, 8.0), BulkTier(20, 7.0)])
        self.assertEqual(tp.unit_price_for(5, 10.0), 10.0)

    def test_tiered_pricing_middle_tier(self):
        tp = TieredPricing([BulkTier(10, 8.0), BulkTier(20, 7.0)])
        self.assertEqual(tp.unit_price_for(15, 10.0), 8.0)

    def test_tiered_pricing_top_tier(self):
        tp = TieredPricing([BulkTier(10, 8.0), BulkTier(20, 7.0)])
        self.assertEqual(tp.unit_price_for(25, 10.0), 7.0)

    def test_price_line(self):
        tp = TieredPricing([BulkTier(10, 8.0)])
        self.assertEqual(tp.price_line(10, 10.0), 80.0)

    def test_apply_markdown(self):
        self.assertEqual(apply_markdown(100.0, 25), 75.0)

    def test_apply_markdown_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            apply_markdown(100.0, 150)

    def test_price_range(self):
        self.assertEqual(price_range([3.0, 1.0, 2.0]), (1.0, 3.0))

    def test_price_range_rejects_empty(self):
        with self.assertRaises(ValueError):
            price_range([])


class DiscountsTest(unittest.TestCase):
    def test_percent_discount(self):
        rule = PercentDiscount(10)
        self.assertEqual(rule.apply(100.0), 90.0)

    def test_flat_discount(self):
        rule = FlatDiscount(15.0)
        self.assertEqual(rule.apply(100.0), 85.0)

    def test_flat_discount_floors_at_zero(self):
        rule = FlatDiscount(150.0)
        self.assertEqual(rule.apply(100.0), 0.0)

    def test_threshold_discount_below_min(self):
        rule = ThresholdDiscount(min_subtotal=50, percent=10)
        self.assertEqual(rule.apply(40.0), 40.0)

    def test_threshold_discount_above_min(self):
        rule = ThresholdDiscount(min_subtotal=50, percent=10)
        self.assertEqual(rule.apply(60.0), 54.0)

    def test_best_discount_picks_lowest(self):
        rules = [PercentDiscount(10), FlatDiscount(50)]
        self.assertEqual(best_discount(100.0, rules), 50.0)

    def test_best_discount_empty_rules(self):
        self.assertEqual(best_discount(100.0, []), 100.0)


class TaxTest(unittest.TestCase):
    def test_default_rate(self):
        table = TaxTable()
        self.assertEqual(table.rate_for("anything"), 0.08)

    def test_category_override(self):
        table = TaxTable(rates={"food": 0.0})
        self.assertEqual(table.rate_for("food"), 0.0)

    def test_tax_for(self):
        table = TaxTable(rates={"food": 0.05})
        self.assertEqual(table.tax_for("food", 200.0), 10.0)

    def test_total_with_tax(self):
        self.assertEqual(total_with_tax(100.0, 0.08), 108.0)


class OrderTest(unittest.TestCase):
    def _make_order(self):
        table = TaxTable(rates={"food": 0.05}, default_rate=0.08)
        order = Order(tax_table=table)
        food = Item(sku="f1", name="Bread", category="food", unit_price=4.0)
        misc = Item(sku="m1", name="Pen", category="misc", unit_price=2.0)
        order.add_line(LineItem(item=food, quantity=3))
        order.add_line(LineItem(item=misc, quantity=5))
        return order

    def test_subtotal(self):
        order = self._make_order()
        self.assertEqual(order.subtotal(), 22.0)

    def test_tax_total(self):
        order = self._make_order()
        self.assertEqual(order.tax_total(), 1.4)

    def test_total_without_discount(self):
        order = self._make_order()
        self.assertEqual(order.total(), 23.4)

    def test_total_with_discount(self):
        order = self._make_order()
        total = order.total(PercentDiscount(50))
        self.assertEqual(total, 11.7)

    def test_item_count(self):
        order = self._make_order()
        self.assertEqual(order.item_count(), 8)

    def test_summary(self):
        order = self._make_order()
        summary = order.summary()
        self.assertEqual(summary["line_count"], 2)
        self.assertEqual(summary["item_count"], 8)


class IoCsvTest(unittest.TestCase):
    def test_export_and_import_catalog_roundtrip(self):
        catalog = Catalog()
        catalog.add(Item(sku="a", name="A", category="misc", unit_price=1.5))
        catalog.add(Item(sku="b", name="B", category="food", unit_price=2.5))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "catalog.csv")
            export_catalog(catalog, path)
            loaded = import_catalog(path)
            self.assertEqual(loaded.get("a").name, "A")
            self.assertEqual(loaded.get("b").unit_price, 2.5)

    def test_import_order_lines_and_export(self):
        catalog = Catalog()
        catalog.add(Item(sku="a", name="A", category="misc", unit_price=1.5))
        with tempfile.TemporaryDirectory() as tmp:
            order_path = os.path.join(tmp, "order.csv")
            with open(order_path, "w", newline="") as f:
                f.write("sku,quantity\na,3\n")
            lines = import_order_lines(order_path, catalog)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].quantity, 3)

            out_path = os.path.join(tmp, "out.csv")
            export_order_lines(lines, out_path)
            with open(out_path) as f:
                content = f.read()
            self.assertIn("a,3", content)


if __name__ == "__main__":
    unittest.main()
