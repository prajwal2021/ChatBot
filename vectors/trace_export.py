from __future__ import annotations

import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status


router = APIRouter(prefix="/api/v1/traces", tags=["traces"])

VALID_AGENTS = {"ttu-online", "k12"}
TRACE_DIR = Path(__file__).parent / "traces"

_DATE_FILE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")


def require_trace_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    configured_key = os.getenv("TRACE_EXPORT_API_KEY", "").strip()
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trace export is not configured",
        )

    scheme, _, supplied_key = (authorization or "").partition(" ")
    valid = (
        scheme.lower() == "bearer"
        and bool(supplied_key)
        and hmac.compare_digest(supplied_key, configured_key)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid trace API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validated_agent(agent: str) -> str:
    if agent not in VALID_AGENTS:
        raise HTTPException(status_code=400, detail="Invalid agent")
    return agent


def _selected_date(date: Optional[str]) -> str:
    selected = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected):
        raise HTTPException(status_code=400, detail="Invalid date")
    return selected


def _read_traces(agent: str, date: str) -> list[dict]:
    path = TRACE_DIR / agent / f"{date}.jsonl"
    try:
        if not path.is_file():
            return []

        traces: list[dict] = []
        with path.open("r", encoding="utf-8") as trace_file:
            for line in trace_file:
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(parsed, dict):
                    traces.append(parsed)
        return traces
    except FileNotFoundError:
        return []
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to read trace file",
        ) from exc


@router.get("/dates")
def list_trace_dates(
    agent: str,
    _: None = Depends(require_trace_api_key),
):
    selected_agent = _validated_agent(agent)
    agent_dir = TRACE_DIR / selected_agent
    try:
        if not agent_dir.is_dir():
            return {"agent": selected_agent, "dates": []}

        dates = []
        for path in agent_dir.iterdir():
            if not path.is_file():
                continue
            match = _DATE_FILE_PATTERN.fullmatch(path.name)
            if match:
                dates.append(match.group(1))
        return {"agent": selected_agent, "dates": sorted(dates, reverse=True)}
    except FileNotFoundError:
        return {"agent": selected_agent, "dates": []}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to read trace file",
        ) from exc


@router.get("")
def list_traces(
    agent: str,
    date: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_trace_api_key),
):
    selected_agent = _validated_agent(agent)
    selected_date = _selected_date(date)
    traces = _read_traces(selected_agent, selected_date)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "agent": selected_agent,
        "date": selected_date,
        "page": page,
        "per_page": per_page,
        "total": len(traces),
        "traces": traces[start:end],
    }


@router.get("/{trace_id}")
def get_trace(
    trace_id: str,
    agent: str,
    date: Optional[str] = None,
    _: None = Depends(require_trace_api_key),
):
    selected_agent = _validated_agent(agent)
    selected_date = _selected_date(date)
    for trace in _read_traces(selected_agent, selected_date):
        if trace.get("trace_id") == trace_id:
            return trace
    raise HTTPException(status_code=404, detail="trace_id not found")
