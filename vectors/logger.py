from __future__ import annotations

import hashlib
import base64
import json
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGS_DIR = Path(__file__).parent / "logs"
_LOGS_DIR.mkdir(exist_ok=True)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _log_file(date_label: str) -> Path:
    return _LOGS_DIR / f"{date_label}.jsonl"


def log_answer_audit(record: dict[str, Any]) -> None:
    """Append one background-verifier comparison. Kept in logs/audit/ so the
    dated interaction logs and their export API are unaffected."""
    audit_dir = _LOGS_DIR / "audit"
    audit_dir.mkdir(exist_ok=True)
    record = {"timestamp": _now_iso(), **record}
    with (audit_dir / "answer_audit.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()


def _append_record(record: dict[str, Any]) -> None:
    with _log_file(_today_label()).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    # Publish only after the durable append so live consumers never see a
    # record that is missing from the historical API.
    from log_stream import publish
    publish(_canonicalize_record(record))


def _canonicalize_record(record: dict[str, Any]) -> dict[str, Any]:
    from agent_ids import canonical_agent_id

    query = record.get("query")
    if not isinstance(query, dict):
        return record
    old_agent = query.get("agent_routed_to")
    new_agent = canonical_agent_id(old_agent) if isinstance(old_agent, str) else old_agent
    if new_agent == old_agent:
        return record
    normalized = dict(record)
    normalized["query"] = {**query, "agent_routed_to": new_agent}
    return normalized


def _encode_cursor(filename: str, line_number: int) -> str:
    raw = json.dumps({"file": filename, "line": line_number}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        filename = value["file"]
        line_number = value["line"]
        if not isinstance(filename, str) or not filename.endswith(".jsonl"):
            raise ValueError
        if not isinstance(line_number, int) or line_number < 0:
            raise ValueError
        return filename, line_number
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid log cursor") from exc


def _timestamp(record: dict[str, Any]) -> datetime | None:
    value = record.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def list_log_records(
    *,
    agent: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Read log records in append order with an opaque file/line cursor."""
    from agent_ids import canonical_agent_id

    if since and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if until and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    cursor_position = _decode_cursor(cursor) if cursor else None
    matched: list[tuple[dict[str, Any], str, int]] = []

    for path in sorted(_LOGS_DIR.glob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            position = (path.name, line_number)
            if cursor_position and position <= cursor_position:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = _canonicalize_record(record)
            record_agent = canonical_agent_id(
                (record.get("query") or {}).get("agent_routed_to", "")
            )
            if agent and record_agent != canonical_agent_id(agent):
                continue
            timestamp = _timestamp(record)
            if since and (timestamp is None or timestamp < since):
                continue
            if until and (timestamp is None or timestamp > until):
                continue
            matched.append((record, path.name, line_number))
            if len(matched) > limit:
                break
        if len(matched) > limit:
            break

    has_more = len(matched) > limit
    page = matched[:limit]
    records = [item[0] for item in page]
    next_cursor = cursor
    if page:
        _, filename, line_number = page[-1]
        next_cursor = _encode_cursor(filename, line_number)
    return records, next_cursor, has_more


def get_log_record(log_id: str) -> dict[str, Any] | None:
    for path in sorted(_LOGS_DIR.glob("*.jsonl"), reverse=True):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("log_id") == log_id:
                return _canonicalize_record(record)
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def log_interaction(
    session_id: str,
    query_text: str,
    agent: str,
    user_ip: str,
    user_agent: str,
    retrieval_result: dict[str, Any],
    response_result: dict[str, Any],
    eval_result: dict[str, Any] | None = None,
) -> str:
    """Write one complete interaction to today's .jsonl file.

    retrieval_result expected keys:
        method              "hybrid" | "qdrant_only" | "bm25_only"
        chunks_retrieved    int
        retrieval_latency_ms  int
        chunks              list of dicts — see schema below

    Each chunk dict:
        chunk_id, source, text, qdrant_score, bm25_score, rank

    response_result expected keys:
        text, model_used, prompt_tokens, completion_tokens,
        tokens_used, llm_latency_ms, total_latency_ms, fallback_triggered

    eval_result: output of evaluator.evaluate_response() — optional, stored as-is.

    Returns the log_id (uuid4 string).
    """
    log_id = str(uuid.uuid4())
    response_text = response_result.get("text", "")

    record: dict[str, Any] = {
        "log_id": log_id,
        "timestamp": _now_iso(),
        "session_id": session_id,
        "query": {
            "text": query_text,
            "length": len(query_text),
            "agent_routed_to": agent,
            "user_ip_hash": _hash_ip(user_ip),
            "user_agent": user_agent,
        },
        "retrieval": {
            "method": retrieval_result.get("method", "hybrid"),
            "chunks_retrieved": retrieval_result.get("chunks_retrieved", 0),
            "retrieval_latency_ms": retrieval_result.get("retrieval_latency_ms", 0),
            "chunks": retrieval_result.get("chunks", []),
        },
        "response": {
            "text": response_text,
            "length": len(response_text),
            "model_used": response_result.get("model_used", "unknown"),
            "prompt_tokens": response_result.get("prompt_tokens", 0),
            "completion_tokens": response_result.get("completion_tokens", 0),
            "tokens_used": response_result.get("tokens_used", 0),
            "llm_latency_ms": response_result.get("llm_latency_ms", 0),
            "total_latency_ms": response_result.get("total_latency_ms", 0),
            "fallback_triggered": response_result.get("fallback_triggered", False),
            "source": response_result.get("source", "llm"),
        },
        "eval_result": eval_result,
        "feedback": None,
        "error": None,
    }

    _append_record(record)
    return log_id


def log_feedback(
    log_id: str,
    feedback_type: str,
    feedback_text: str | None,
    log_date: str,
) -> bool:
    """Find a logged interaction by log_id and update its feedback field in-place.

    log_date must be "YYYY-MM-DD" (UTC) matching the file the interaction was written to.
    feedback_type: "thumbs_up" | "thumbs_down"
    Returns True if the record was found and updated, False otherwise.
    """
    log_file = _log_file(log_date)
    if not log_file.exists():
        return False

    lines = log_file.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        if record.get("log_id") == log_id:
            record["feedback"] = {
                "type": feedback_type,
                "text": feedback_text,
                "timestamp": _now_iso(),
            }
            new_lines.append(json.dumps(record, ensure_ascii=False))
            updated = True
        else:
            new_lines.append(line)

    if updated:
        log_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return updated


def log_error(
    session_id: str,
    query_text: str,
    agent: str,
    user_ip: str,
    user_agent: str,
    error: Exception,
    error_type: str = "unknown",
    component: str = "unknown",
    severity: str = "error",
) -> str:
    """Write a failed interaction where retrieval and response are null.

    error_type: "qdrant_timeout" | "llm_api_error" | "bm25_failure" | "rate_limit" | "unknown"
    component:  "retrieval" | "llm" | "api"
    severity:   "warning" | "error" | "critical"

    Returns the log_id (uuid4 string).
    """
    log_id = str(uuid.uuid4())

    record: dict[str, Any] = {
        "log_id": log_id,
        "timestamp": _now_iso(),
        "session_id": session_id,
        "query": {
            "text": query_text,
            "length": len(query_text),
            "agent_routed_to": agent,
            "user_ip_hash": _hash_ip(user_ip),
            "user_agent": user_agent,
        },
        "retrieval": None,
        "response": None,
        "feedback": None,
        "error": {
            "type": error_type,
            "message": str(error),
            "component": component,
            "severity": severity,
            "stack_trace": traceback.format_exc(),
            "timestamp": _now_iso(),
        },
    }

    _append_record(record)
    return log_id
