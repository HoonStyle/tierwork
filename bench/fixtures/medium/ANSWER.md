# Pre-registered defects

Format: `ID|path:allowed-line-range|condition|expected behavior`.

medium-tax-fallback|inv/tax.py:15-17|category has no override|return self.default_rate without NameError
medium-pricing-tier|inv/pricing.py:29-31|quantity reaches the highest tier|consider the final tier price
medium-discount-key|inv/io_csv.py:49-51|CSV row contains discount_pct|preserve the supplied discount
medium-rounding-args|inv/order.py:30-32|subtotal is rounded|pass amount before rounding mode
