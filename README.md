# tierwork

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-D97757)](#claude-code)
[![Codex plugin](https://img.shields.io/badge/Codex-plugin-000000)](#codex)
[![Python 3 utilities](https://img.shields.io/badge/Python-3_utilities-3776AB?logo=python&logoColor=white)](#logs-and-dashboard)

Task-based model delegation and review logging for Claude Code and OpenAI Codex CLI.

Tierwork provides a delegation skill, review-agent definitions, lifecycle hooks, and a local dashboard. It helps assign review work to model tiers and track the resulting runs. It does **not** independently schedule agents or guarantee lower cost or better findings.

[Install](#install) · [Usage](#usage) · [Review workflow](#review-workflow) · [Logs and dashboard](#logs-and-dashboard) · [Compatibility and limitations](#compatibility-and-limitations) · [Development](#development)

## Features

- **Task-based delegation:** use different model tiers for eligibility checks, compliance review, bug hunting, and validation.
- **Review agents:** Claude Code definitions for `gate`, `compliance-reviewer`, `bug-hunter`, and `bug-validator`; manual Codex templates for the same roles.
- **Session policy:** a `SessionStart` hook supplies a condensed delegation policy.
- **Run logging:** lifecycle hooks record starts, completions, available token counts, and validator verdicts locally.
- **Status and dashboard:** inspect recorded work, label findings, and export or merge logs across machines.

## Install

### Claude Code

Run in Claude Code:

```text
/plugin marketplace add HoonStyle/tierwork
/plugin install tierwork@tierwork
```

Start a fresh session after installation. For a local checkout:

```bash
claude --plugin-dir /path/to/tierwork
claude plugin validate /path/to/tierwork
```

### Codex

Register and install a local checkout:

```bash
codex plugin marketplace add /path/to/tierwork
codex plugin add tierwork@tierwork
```

Review and trust the plugin hooks through `/hooks` in the Codex TUI. Installation alone does not authorize hooks to run.

Codex does not automatically load the plugin's agent definitions. Copy the templates into the **target project**, then edit each template's `model` field to a model available in your environment:

```bash
mkdir -p /path/to/project/.codex/agents
cp /path/to/tierwork/codex/agents/*.toml /path/to/project/.codex/agents/
```

The shipped model IDs are placeholders. The local-marketplace installation was verified with Codex CLI 0.153.0; installing the marketplace directly from GitHub remains unverified in the recorded checks.

## Usage

Once installed, ask the host to apply the delegation skill. For example:

```text
Review the current diff using tierwork's subagent-delegation policy.
Check review eligibility, delegate compliance and bug review separately,
validate each candidate, and report confirmed findings with evidence.
```

This is an example prompt, not a new slash command. The host remains responsible for launching agents, collecting their results, and integrating findings.

## Review workflow

| Role | Responsibility | Claude Code tier |
| --- | --- | --- |
| `gate` | Review eligibility and applicable CLAUDE.md paths | Haiku |
| `compliance-reviewer` | Repository-instruction compliance | Sonnet |
| `bug-hunter` | Two parallel lenses: diff-only and introduced logic | Opus |
| `bug-validator` | Validate individual candidates; deterministic checks before judgment | Opus for bugs, Sonnet for compliance |

Validators report `check_status: passed|failed|unavailable`. The no-reopen fast path requires `confirmed`, a passed deterministic check, and confidence ≥ 70; confidence alone does not qualify an unchecked finding.

Model tiers follow **task type**, not diff size. The gate does not select a model tier. The parent retains assignment handles and distinguishes completion observed, result retrieved, and result integrated.

See the [delegation skill](skills/subagent-delegation/SKILL.md), [session policy](hooks/policy.md), and [agent definitions](agents/).

## Unified local dashboard

The bundled [Plugin Desk](dashboard/README.md) shows Greplet search/index status,
Legacy Spec documents, and Tierwork agent records in one local dashboard, with
specialized views for each tool and an event-driven dinosaur runner.
No separate dashboard installation or npm dependencies are needed. With Node.js
22 or later, run `node dashboard/server.mjs` from this repository and open
`http://127.0.0.1:8787`. Configure source paths in `dashboard/config.json`;
the default expects `legacy-spec-agent` beside the Tierwork checkout and Greplet
at `http://127.0.0.1:7802`. The existing Python review dashboard remains available.

Validate with `node --test dashboard/test.mjs dashboard/test-ui.mjs`.

## Logs and dashboard

Run the following from the tierwork checkout:

```bash
python3 bench/report.py
python3 bench/status.py --json
python3 bench/dashboard.py
```

Open the URL printed by the dashboard. It binds to `127.0.0.1` and defaults to port `8765`.

| Setting | Default | Purpose |
| --- | --- | --- |
| `TIERWORK_LOG` | `~/.tierwork/reviews.jsonl` | Run log; set before starting the agent host |
| Dashboard `--labels` | `~/.tierwork/labels.jsonl` | Manual true/false-positive labels, stored separately |
| Dashboard `--port` | `8765` | Local web port |

Optional auto-start is disabled until explicitly enabled:

```bash
python3 bench/dashboard-service.py enable
python3 bench/dashboard-service.py status
# To remove auto-start:
python3 bench/dashboard-service.py disable
```

The service uses launchd, Windows Task Scheduler, or a systemd user service, depending on the OS. Python 3 is required for these utilities and Codex log parsing; the Claude logging hook also has jq/minimal fallbacks. The log hook is non-blocking and may record incomplete data when a transcript or parser is unavailable. The no-Python/no-jq minimal fallback records lifecycle identity and status only, not validator check results.

Recorded status merges use the latest valid timestamp; completion wins only on a timestamp tie. Future-dated or unknown states are not treated as completed work. The dashboard buffers incomplete JSONL records and reports rejected complete records at `/api/diagnostics`.

Logs can contain project metadata and model usage. Review them before exporting or sharing. Details on routes, labels, multi-source input, and exports are in the [bench guide](bench/README.md).

## Compatibility and limitations

- **Claude Code:** installation, policy visibility, and the four agents were verified in a fresh session on 2026-09-04. Hook-policy propagation into every sub-agent context remains unverified.
- **Codex:** local installation and one trusted-hook session were verified on 2026-09-04. Mapping agents spawned from project TOML templates to tierwork role names remains unverified.
- **Recorded status is not process liveness.** A completion row does not prove the parent retrieved or integrated the result. Hooks cannot wake a waiting parent.
- **Live multi-agent acceptance remains pending.** Mechanical tests and one-shot hook observations do not establish every harness behavior.
- **No general efficiency claim.** Early small-fixture comparisons include runs that cost more or took longer without improving findings. They are version-specific observations, not a performance guarantee.

Historical runtime observations, counter assumptions, measurements, and release notes are preserved in [README-history.md](README-history.md). Later entries can supersede earlier ones.

## Development

Focused checks from the repository root:

```bash
python3 -m unittest discover -s bench -p 'test_*.py'
claude plugin validate .
git diff --check
```

The [bench guide](bench/README.md) describes the A/B harness and its limitations. Its small fixture is an intentional historical policy snapshot, not the current validator contract; keeping it unchanged preserves the meaning of previous measurements. Full live harness acceptance requires actual Claude Code and trusted-hook Codex sessions; it is not replaced by unit tests.

## Prompt changelog

### 0.9.1 — Task-contract boundary

- Goal: prevent general delegation optimizations from changing document-workflow
  requirements; distinguish reused checks from new verification.
- Target: Claude Code/Codex host orchestrators and users of the shared delegation
  skill; model-independent. No model/version change or live model acceptance run
  accompanies this revision. Existing review-agent tiers remain unchanged.
- Files: `hooks/policy.md`, `skills/subagent-delegation/SKILL.md`.
- Before → after (changed guidance):
  - “Pass intent and pointers … not bulk content” → code-review preference only;
    preserve required inline content or accessible packets under the task contract.
  - “a producer never verifies its own output” → independent validation stays
    isolated; authorized primary self-review is explicitly labeled self-review.
  - “Stop launching further sub-agents once remaining results cannot change the
    decision” → optional work only; mandatory stages cannot be skipped.
  - “primary agent renders artifacts and agents never write them” → preserve the
    task's artifact writer and required format; typed output is the fallback.
  - “do not repeat the same verification from scratch” → reuse only within the
    recorded version/scope/assumptions; recheck affected claims after changes.
  - Previously unspecified → no arbitrary read limits or silent scope/restart
    changes; record interruption state and recover the affected remainder.
  - Previously unspecified → missing evidence is unknown, not absence; latest
    accepted corrections supersede historical restrictions.
  - Previously unspecified → completion reports distinguish executor, input
    version, reuse, new checks, and gaps; no unmeasured counterfactual savings.
- Reason: an inspected document-workflow incident showed actual source reads,
  repeated work, changing restrictions, and overstated completion. It does not
  establish that pointers alone caused the cost or that inline input saves a
  particular amount. No private transcript or career data is included here.
- Validation: static contract regression checks plus the existing mechanical
  suite. These guard prompt text, not model compliance or efficiency; live
  document-workflow acceptance remains pending. Validator schemas and historical
  benchmark fixtures are unchanged.

## Repository layout

```text
skills/subagent-delegation/  Shared delegation workflow
agents/                     Claude Code review agents
codex/agents/               Manual Codex agent templates
hooks/                      Session policy and local logging
bench/                      Dashboard, status, reports, tests, and A/B harness
.claude-plugin/             Claude Code plugin and marketplace manifests
.codex-plugin/              Codex plugin manifest
.agents/plugins/           Local Codex marketplace manifest
```

## Roadmap and contributing

Migration work is tracked in the [shared roadmap](docs/migration-roadmap.md) and [Greplet evidence release plan](docs/greplet-evidence-v1.md). Planned migration verification is not a shipped capability merely because it appears in those documents.

For bug reports, include the host and plugin versions, a minimal reproduction, and relevant redacted logs. Keep fixture measurements separate from live-session results and proposed behavior separate from implemented behavior.

## License

[MIT](LICENSE)
