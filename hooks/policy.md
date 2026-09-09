# Tierwork delegation policy

## Task-contract boundary

- Tierwork is an efficiency default, not a replacement for the active task
  contract. Subject to higher-priority instructions, preserve project/user
  requirements for inputs, mandatory stages, evidence, artifacts, and executor.
  Code-review gates, fan-out, isolation, and report limits apply to code review,
  not automatically to document editing or other workflows. User-authorized
  primary self-review must be labeled self-review, not independent validation.
- Preserve required content whether inline or in an accessible input packet;
  use pointers only when the task permits them and the recipient can read the
  required content. A path alone is not evidence of a completed read. Never
  invent read-count limits or omit mandatory stages to save tokens.
- Do not silently change scope or restart assignments. Record the reason and
  affected stage/version; resume available work first. After interruption,
  distinguish partial, cancelled, blocked, and completed work; recover only the
  affected remainder, subject to the user's latest instructions.
- Reuse checks only for matching artifact version, scope, and assumptions.
  Recheck affected claims after changes; label reused versus newly performed
  checks, including executor, input version, evidence, and gaps. Concise status
  summaries do not replace required output packets or artifacts. Claim workflow
  completion only for the stages actually satisfied under the active contract.
- Missing evidence means unknown, not false or absent. Apply the task's accepted
  evidence rules and latest explicit corrections; do not revive superseded
  restrictions from historical reports. Report blocked verification honestly.
- Report measured usage with its source and scope, separately from estimates.
  Do not equate reported tokens with billed cost or avoidable waste, or claim
  counterfactual savings without a comparable measurement.

## Delegation defaults (within that boundary)

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
- Cost (Anthropic API list price/1M tokens, input/output, as of 2026-06-24):
  haiku 4.5 $1/$5 · sonnet 5 $2/$10 · opus 5 $5/$25 · fable 5.1 $10/$50.
  Rule of thumb: opus ~2.5x sonnet, ~5x haiku per token.
- Choose tier by (output volume) x (cost of a wrong answer): high volume/low
  stake -> haiku; default -> sonnet; low volume/high stake -> opus. Never
  put opus on bulk reading/listing; a cheaper agent needing retries is not
  cheaper.
- Before a multi-model cascade, try lower `effort` on the same model first;
  one model keeps one prompt-cache namespace.
- One sub-agent per independent lens; never launch several agents on the same
  question.
- For code review, prefer intent and pointers (title/description, file paths,
  cited locations) over bulk content, subject to the task-contract boundary.
- For independent validation, isolate verifiers from producers: a verifier
  re-derives its verdict from cited evidence, never trusts the producer's
  description; a producer cannot supply independent validation of its own output.
- Sub-agent reports must include: conclusions, file:line evidence, a
  confidence score or level, and explicit gaps/blockers.
- Deterministic checks gate LLM verdicts, never the reverse.
- Supervise every background assignment: retain its current handle/agent ID and
  assignment generation; while waiting, use harness-native wait/status calls in
  bounded approximately 20–30 second windows; collect each terminal result at
  the next opportunity rather than waiting for the full batch.
- Track completion observed, result retrieved, and result integrated separately.
  Reconcile all outstanding assignments before the final answer. Silence alone
  never authorizes cancellation or a duplicate launch.
- Tierwork `running`/`done` hook rows are recorded diagnostics, not process
  liveness or proof of successful result collection. A session-and-agent-matched
  `done` row triggers harness-native retrieval; hook absence is inconclusive.
  Never recover from an arbitrary recent transcript.

Code-review order (follows claude-code /code-review; tiers by task type,
not by diff size):
1. `tierwork:gate` (haiku): eligibility + CLAUDE.md paths. Stop if not eligible.
2. In parallel: `tierwork:bug-hunter` x2 (opus; `lens: diff-only` and
   `lens: introduced-logic`), plus `tierwork:compliance-reviewer` (sonnet)
   when gate returned any CLAUDE.md path.
3. One `tierwork:bug-validator` per bug finding (opus). Compliance findings
   are validated by a sonnet compliance-reviewer instance, not by opus.
4. Primary integration rules: the no-reopen fast path requires all three:
   `verdict: confirmed`, `check_status: passed`, and confidence >= 70. Report
   those findings from the validator's file:line and evidence verbatim. Read
   code yourself for `needs_primary_review: yes`, missing/unknown
   `check_status`, `check_status: unavailable`, or any inconsistent output.
   A failed check refutes the finding regardless of confidence. Final report:
   at most three lines per finding. Recall comes from the two hunter lenses,
   not from the primary re-reading the diff.

Before designing any fan-out of 3+ sub-agents, load the `subagent-delegation`
skill for the full guideline.
