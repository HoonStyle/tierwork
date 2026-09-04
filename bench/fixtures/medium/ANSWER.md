# Answer key — planted bugs in medium fixture's uncommitted diff

(Copied/adapted from repo2-BUGS.md, one bug per file:line.)

1. **inv/tax.py:16** — `TaxTable.rate_for` fallback branch returns the
   undefined name `default_rate` instead of `self.default_rate`; raises
   `NameError` for any category not in `self.rates`.
2. **inv/pricing.py:30** — `TieredPricing.unit_price_for` iterates
   `range(tier_count - 1)` instead of `range(tier_count)`, so the last
   (highest) bulk-price tier is never considered.
3. **inv/io_csv.py:50** — `import_order_lines` reads the discount with
   `row.get("discont_pct", 0)`, a typo'd key (should be `discount_pct`), so
   any CSV discount is silently dropped.
4. **inv/order.py:31** — `Order.subtotal` calls
   `round_amount(self.rounding, total)` with the arguments swapped;
   `round_amount(value, mode)` expects the amount first and the rounding
   mode second.
