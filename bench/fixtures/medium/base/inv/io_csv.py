"""CSV import/export for catalogs and orders, using only the stdlib."""

import csv

from .models import Catalog, Item, LineItem


CATALOG_FIELDS = ["sku", "name", "category", "unit_price"]
ORDER_FIELDS = ["sku", "quantity"]


def export_catalog(catalog: Catalog, path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        for item in catalog.all_items():
            writer.writerow(
                {
                    "sku": item.sku,
                    "name": item.name,
                    "category": item.category,
                    "unit_price": item.unit_price,
                }
            )


def import_catalog(path: str) -> Catalog:
    catalog = Catalog()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = Item(
                sku=row["sku"],
                name=row["name"],
                category=row["category"],
                unit_price=float(row["unit_price"]),
            )
            catalog.add(item)
    return catalog


def import_order_lines(path: str, catalog: Catalog):
    lines = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = catalog.get(row["sku"])
            quantity = int(row["quantity"])
            lines.append(LineItem(item=item, quantity=quantity))
    return lines


def export_order_lines(lines, path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ORDER_FIELDS)
        writer.writeheader()
        for line in lines:
            writer.writerow({"sku": line.item.sku, "quantity": line.quantity})
