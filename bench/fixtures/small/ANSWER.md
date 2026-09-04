# Answer key — planted bugs in small fixture's uncommitted diff

1. **tools/usage.py:16** — typo `"asistant"` instead of `"assistant"` in the
   type check, so the record filter never matches and `totals()` always
   returns empty.
2. **tools/usage.py:22** — undefined name `usage` (should be `u`, the local
   variable already bound above), causing a `NameError` on every call.
