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
  finder, Opus validator).
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

## Unverified items

1. Whether `SessionStart` hook stdout reaches Claude Code sub-agents (the
   docs describe sub-agent initial context without mentioning this).
2. What working directory Codex uses when running a plugin hook command
   (whether `${CLAUDE_PLUGIN_ROOT}` fallback of `.` in
   `hooks/session-start.sh` resolves correctly under Codex).
3. Whether the `.agents/plugins/marketplace.json` entry shape used here
   (`source: {source: "local", path: "./"}` at the plugin root, rather than
   the `./plugins/<name>` convention shown in the Codex plugin-creator
   reference) is accepted by Codex's marketplace loader.
4. The Codex model ids in `codex/agents/*.toml` (`gpt-5.6` is a placeholder
   marked with a `# TODO` comment — verify a current Codex model id before
   use).
5. Whether Codex's third-party plugin validator accepts a plugin whose
   marketplace entry lives under `.agents/plugins/` at the plugin's own repo
   root, as opposed to a separate personal (`~/.agents/plugins/`) or
   repo/team marketplace file.

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

- 0.1.0 (2026-09-04): initial release. Cost rules added; bug-validator runs
  deterministic checks before LLM judgment (arXiv:2609.02246); deterministic
  checks are a hard gate; discovered-context reuse rule; versioning rule.
