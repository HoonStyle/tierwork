# Tierwork delegation policy

- The primary agent owns prioritization, integration, final judgment, and
  verification. Delegate bounded, independent subtasks to sub-agents; do not
  delegate trivial work.
- Model tier:
  - `haiku` — gating/eligibility checks, listing file paths, formulaic or
    high-frequency work.
  - `sonnet` — the default for review, analysis, exploration, and
    summarization.
  - `opus` — bug finding, validation of findings, behavior-preserving
    simplification, and any task where a wrong answer is expensive.
  - Default to `inherit` when unsure which tier a subtask needs.
- Cost (Anthropic API list price, per 1M tokens, input/output, as of 2026-06-24;
  subscription plans meter differently, but ratios still drive limit burn):
  haiku 4.5 $1/$5 · sonnet 5 $2/$10 · opus 5 $5/$25 · fable 5.1 $10/$50.
  Rule of thumb: opus ~2.5x sonnet, ~5x haiku per token.
- Choose tier by (output volume) x (cost of a wrong answer): high volume/low
  stake -> haiku; default -> sonnet; low volume/high stake -> opus. Never put
  opus on bulk reading/listing. Judge cost per completed task: a cheaper
  agent needing retries is not cheaper.
- Before a multi-model cascade, try lower `effort` on the same model first;
  one model keeps one prompt-cache namespace.
- One sub-agent per independent lens; never launch several agents on the same
  question.
- Pass intent and pointers (title/description, file paths, cited locations),
  not bulk content, to sub-agents.
- Isolate verifiers from producers: a verifier re-derives its verdict from the
  cited code, never trusts the producer's description, and a producer never
  verifies its own output.
- Sub-agent reports must include: conclusions, file:line evidence, a
  confidence score or level, and explicit gaps/blockers.
- Deterministic checks gate LLM verdicts, never the reverse.

Shipped agents (Claude only, scoped names):
- `tierwork:gate` (haiku) — eligibility gate + CLAUDE.md file path listing.
- `tierwork:compliance-reviewer` (sonnet) — CLAUDE.md compliance audit.
- `tierwork:bug-hunter` (opus) — diff-only or introduced-logic bug scanning.
- `tierwork:bug-validator` (opus) — re-derives the verdict for one finding.

Before designing any fan-out of 3+ sub-agents, load the `subagent-delegation`
skill for the full guideline.
