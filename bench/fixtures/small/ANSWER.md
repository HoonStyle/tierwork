# Pre-registered defects

Format: `ID|path:allowed-line-range|condition|expected behavior`.

small-filter|tools/usage.py:15-17|any non-empty assistant record list|assistant records contribute to totals
small-usage-name|tools/usage.py:21-23|calling totals after a matched record|the bound usage object is accumulated without NameError
