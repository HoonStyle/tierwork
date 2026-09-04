#!/usr/bin/env bash
# Prints the tierwork delegation policy to stdout as plain text.
# Both Claude Code and Codex CLI add SessionStart stdout as context.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat "$DIR/policy.md"

exit 0
