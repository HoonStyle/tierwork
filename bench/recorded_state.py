"""Shared recorded-state semantics for Tierwork log consumers.

The result describes the latest hook event we can record for an assignment;
it is not authoritative process liveness. Assignment generations are not
present in the log format, so a reused ``(session_id, agent_id)`` remains an
explicit limitation rather than something inferred here.
"""

from datetime import datetime, timezone


KNOWN_STATUS = {"running", "done"}


def parse_ts(value):
    """Parse an ISO timestamp as UTC, returning ``None`` when invalid."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def identity_key(row):
    """Return a usable assignment identity, or ``None`` when incomplete."""
    session_id = row.get("session_id")
    agent_id = row.get("agent_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None
    return session_id, agent_id


def recorded_status(row):
    """Normalize a status without turning future values into completion.

    Rows written before the start hook have no ``status`` field and represent
    completed stop records, so missing/``None`` remains the one legacy alias
    for ``done``. Any other unrecognized value is deliberately ``unknown``.
    """
    status = row.get("status")
    if status is None:
        return "done"
    if status in KNOWN_STATUS:
        return status
    return "unknown"


def latest_recorded(rows):
    """Return the latest valid event for every recorded assignment.

    A valid timestamp is the primary ordering key. Only when timestamps are
    equal does a completed/legacy stop record beat another state. Input order
    resolves all remaining ties, making later-loaded rows deterministic.
    """
    latest = {}
    skipped = {"invalidIdentity": 0, "invalidTimestamp": 0}
    for index, row in enumerate(rows):
        key = identity_key(row)
        if key is None:
            skipped["invalidIdentity"] += 1
            continue
        parsed = parse_ts(row.get("ts"))
        if parsed is None:
            skipped["invalidTimestamp"] += 1
            continue
        done_tie_rank = 1 if recorded_status(row) == "done" else 0
        candidate = (parsed, done_tie_rank, index, row)
        if key not in latest or candidate[:3] >= latest[key][:3]:
            latest[key] = candidate
    return [value[3] for value in latest.values()], skipped
