# tierwork

## What it is

Tierwork is a plugin usable by both Claude Code and OpenAI Codex CLI. It
ships:

- A sub-agent delegation guideline (which model tier to use for which
  subtask) as a skill (`subagent-delegation`).
- A short delegation policy injected at session start via a `SessionStart`
  hook.
- Four agent definitions for Claude Code (`gate`, `compliance-reviewer`,
  `bug-hunter`, `bug-validator`), modeled on the claude-code repo's
  `/code-review` command pattern (Haiku gate, Sonnet compliance, Opus bug
  finder, Opus validator). The gate also sizes the diff and returns
  `review_tier`/`validation_tier`, used as per-spawn model overrides for
  bug-hunter/bug-validator; gate now runs in parallel with a
  provisional-tier bug-hunter instead of strictly before it, and only an
  opus second-pass hunter is launched when gate finds a stake signal.
- Template Codex sub-agent `.toml` files with the same instructions, for
  manual copy into a project's `.codex/agents/` (Codex does not load plugin
  agent definitions automatically).

## Layout

```
tierwork/
├── .claude-plugin/plugin.json        # Claude Code plugin manifest
├── .claude-plugin/marketplace.json   # Claude Code marketplace entry
├── .codex-plugin/plugin.json         # Codex plugin manifest
├── .agents/plugins/marketplace.json  # Codex marketplace entry (untested, see below)
├── hooks/hooks.json                  # SessionStart hook wiring (shared format)
├── hooks/session-start.sh            # prints hooks/policy.md to stdout
├── hooks/policy.md                   # condensed delegation policy
├── skills/subagent-delegation/SKILL.md  # full guideline (shared: skills work in both tools)
├── agents/*.md                       # Claude Code agent definitions
└── codex/agents/*.toml               # Codex agent templates (copy manually)
```

## Install for Claude Code

```
/plugin marketplace add HoonStyle/tierwork
/plugin install tierwork@tierwork
```

Local testing before publishing:

```
claude --plugin-dir ./tierwork
claude plugin validate ./tierwork
/reload-plugins
```

## Install for Codex

```
codex plugin marketplace add ./tierwork
# or, once pushed:
codex plugin marketplace add HoonStyle/tierwork --ref main
codex plugin add tierwork@tierwork
```

The `subagent-delegation` skill and the `SessionStart` hook are picked up
automatically. Codex does not load agent definitions from a plugin, so copy
the templates manually:

```
cp codex/agents/*.toml .codex/agents/
```

Edit the `model` field in each copied `.toml` first — the shipped value is a
placeholder (see "Unverified items" below).

## What is shared vs tool-specific

- **Shared:** `skills/subagent-delegation/SKILL.md` (frontmatter limited to
  `name` and `description` for Codex compatibility) and the general
  `hooks/hooks.json` + `hooks/session-start.sh` + `hooks/policy.md` shape.
  `hooks/session-start.sh` resolves `${CLAUDE_PLUGIN_ROOT}` with a `.`
  fallback, which assumes Codex runs the hook command with cwd set to the
  plugin root — **UNVERIFIED**.
- **Claude-only:** `agents/*.md` (loaded automatically as
  `tierwork:gate`, `tierwork:compliance-reviewer`, `tierwork:bug-hunter`,
  `tierwork:bug-validator`).
- **Codex-only (manual):** `codex/agents/*.toml` templates — not loaded from
  the plugin; copy into a project's `.codex/agents/`.

## Verified on 2026-09-04

- Claude Code: `claude plugin validate` passes; installed via
  `/plugin marketplace add HoonStyle/tierwork` + `/plugin install tierwork@tierwork`;
  a fresh session (no `--plugin-dir`) sees the policy section and all four
  `tierwork:` agents.
- Codex CLI 0.153.0: `codex plugin marketplace add <local path>` and
  `codex plugin add tierwork@tierwork` succeed; `codex plugin list` shows it
  installed and enabled. The `.agents/plugins/marketplace.json` shape with
  `source: {source: "local", path: "./"}` is therefore accepted.

## Unverified items

1. Whether `SessionStart` hook stdout reaches Claude Code sub-agents (the
   docs describe sub-agent initial context without mentioning this).
2. What working directory Codex uses when running a plugin hook command
   (whether the `${CLAUDE_PLUGIN_ROOT}` fallback of `.` in
   `hooks/session-start.sh` resolves correctly under Codex), and whether the
   policy and skill are actually visible inside a Codex session. Install
   succeeded, but a runtime check could not be run (workspace had no credits).
3. The Codex model ids in `codex/agents/*.toml` (`gpt-5.6` is a placeholder
   marked with a `# TODO` comment; verify a current Codex model id before
   use).
4. Installing the Codex marketplace from GitHub
   (`codex plugin marketplace add HoonStyle/tierwork --ref main`) rather than
   a local path.

## Sources

- code.claude.com/docs: plugins-reference, hooks, sub-agents,
  plugin-marketplaces.
- developers.openai.com/codex: plugins, hooks, subagents, skills.
- anthropics/claude-code: `plugins/code-review/commands/code-review.md`.
- arXiv:2609.02246, "LLM-as-a-Judge Is Not an Oracle: Why Self-Improving
  Agents Need Deterministic Guardrails".
- arXiv:2609.02248, "From Prompting to Engineering: A Research Agenda for
  Prompt Engineering in Software Engineering".
- arXiv:2609.02129, "Beyond Context Windows: Persistent Discovery Context for
  Data-Centric Agents".
- Reviewed, not applied: Google Cloud zero-shot / data-driven prompt
  optimizer docs (no cost data).
- Anthropic API pricing: https://docs.anthropic.com/en/docs/about-claude/pricing

## Changelog

- 0.3.2 (2026-09-04): policy: validators must wait for the gate result and never use the default model (run E launched opus validators although gate returned sonnet).

- 0.3.1 (2026-09-04): fix: removed `hooks` from `.claude-plugin/plugin.json`. Claude Code auto-loads `hooks/hooks.json`; naming it again in the manifest makes the loader report "Duplicate hooks file detected" and mark the plugin failed to load (seen on 0.2.1 and 0.3.0, macOS and Windows). Reported by the user from another machine.

- 0.3.0 (2026-09-04): bug-validator maxTurns 12 (run D had a 30-turn
  validator), bug-hunter maxTurns 15; gate now runs in parallel with a
  provisional-tier bug-hunter, and only a stake signal triggers an opus
  second pass. Motivated by run D wall time (175 s).

- 0.2.1 (2026-09-04): gate made mandatory first step in policy and in bug-hunter/bug-validator descriptions; Run C had skipped it.

- 0.1.0 (2026-09-04): initial release. Cost rules added; bug-validator runs
  deterministic checks before LLM judgment (arXiv:2609.02246); deterministic
  checks are a hard gate; discovered-context reuse rule; versioning rule.
- 0.2.0 (2026-09-04): gate sizes the diff and returns review_tier/validation_tier;
  primary passes them as per-spawn model overrides. Thresholds: small <=3
  files/<=60 lines -> sonnet+sonnet; medium <=10 files/<=400 lines ->
  opus+sonnet; large or any stake signal -> opus+opus. Motivated by the n=1
  measurement; thresholds unmeasured.

## Measurement log

### 2026-09-04, n=1, same task with plugin off vs on

Task: review a 3-line uncommitted diff with two planted bugs (undefined name,
string typo) in a scratch repo; prompt and main model (`opus`) identical;
`claude -p --output-format json`. Both runs found both bugs.

| | plugin off | plugin on |
|---|---|---|
| sub-agents | 2 × sonnet (general-purpose) | 1 × `tierwork:bug-hunter` + 2 × `tierwork:bug-validator` (opus) |
| output tokens (all models) | 10,488 | 11,236 |
| cache read tokens | 1,276,776 | 621,413 |
| reported cost (USD) | 0.83 | 0.98 |
| wall time | 17 s | 154 s |

Reading: on a tiny, low-stake diff the opus validators cost more than the
sonnet baseline and were ~9x slower, with no difference in findings. This is
one observation, not a trend. Confound: the baseline session already had a
user-level instruction to delegate to sonnet, so it was not a naive baseline.
Follow-up: make the gate agent size the validation tier by diff size and
stake instead of always using opus validators.

### 2026-09-04, runs C and D (0.2.x), same task

| run | plugin | sub-agents (model actually used) | cost (USD) | wall | findings |
|---|---|---|---|---|---|
| A | off | 2 × sonnet | 0.83 | 17 s | 2/2 |
| B | 0.1.0 | hunter + 2 validators, all opus | 0.98 | 154 s | 2/2 |
| C | 0.2.0 | hunter + 2 validators, all opus (gate skipped) | 0.96 | 158 s | 2/2 |
| D | 0.2.1 | gate haiku, hunter sonnet, 2 validators sonnet | 0.73 | 175 s | 2/2 |

Reading: in C the primary skipped gate because the policy did not make it
mandatory; 0.2.1 fixed the wording and D followed the intended path. D is the
cheapest run but the slowest; the extra wall time is the serial gate step plus
one validator that took 30 turns. Still n=1 per configuration. Main-session
opus tokens are part of every run's cost and are unaffected by the plugin.
