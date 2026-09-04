#!/usr/bin/env bash
# Shared helper: find a real Python 3 interpreter.
#
# `command -v python3` is not trustworthy on its own: on Windows, `python3`
# and/or `python` can be Microsoft Store stubs that either open the Store
# app or exit non-zero without doing anything useful, and hang instead of
# returning promptly. So every candidate is probed by actually running it
# and checking its output, with a timeout guard.
#
# Candidate order: python3, python, "py -3" (the Windows py launcher, which
# is the real interpreter even when python3/python are Store stubs).
#
# Usage: PY_CMD="$(find_python)" — on success prints a single command
# (space-separated for "py -3") to stdout and returns 0; on failure returns
# 1 and prints nothing.

_tierwork_probe_python() {
  # $1 = interpreter, remaining args = extra args (e.g. "-3" for py).
  local interp="$1"; shift
  local out
  if command -v timeout >/dev/null 2>&1; then
    out="$(timeout 5 "$interp" "$@" -c 'import sys; print(sys.version_info[0])' </dev/null 2>/dev/null)"
  else
    out="$("$interp" "$@" -c 'import sys; print(sys.version_info[0])' </dev/null 2>/dev/null)"
  fi
  [ "$out" = "3" ]
}

find_python() {
  if _tierwork_probe_python python3; then
    printf '%s' "python3"
    return 0
  fi
  if _tierwork_probe_python python; then
    printf '%s' "python"
    return 0
  fi
  if _tierwork_probe_python py -3; then
    printf '%s' "py -3"
    return 0
  fi
  return 1
}
