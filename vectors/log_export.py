from __future__ import annotations

import asyncio
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from agent_ids import canonical_agent_id
from agents_config import AGENTS
from log_stream import subscribe, unsubscribe
from logger import get_log_record, list_log_records


router = APIRouter(prefix="/api/v1/logs", tags=["log-export"])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def require_log_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    configured_key = os.getenv("LOG_EXPORT_API_KEY", "").strip()
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log export is not configured",
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
            detail="Missing or invalid log API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validated_agent(agent: Optional[str]) -> Optional[str]:
    if agent is None:
        return None
    canonical = canonical_agent_id(agent)
    if canonical not in AGENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent '{agent}'. Available: {list(AGENTS)}",
        )
    return canonical


@router.get("")
def export_logs(
    agent: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(require_log_api_key),
):
    if since and until and _aware(since) > _aware(until):
        raise HTTPException(status_code=400, detail="'since' must be before 'until'")
    try:
        records, next_cursor, has_more = list_log_records(
            agent=_validated_agent(agent),
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "data": records,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(records),
    }


@router.get("/stream")
async def stream_logs(
    request: Request,
    agent: Optional[str] = None,
    _: None = Depends(require_log_api_key),
):
    selected_agent = _validated_agent(agent)
    subscriber = subscribe()

    async def events():
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    record = await asyncio.wait_for(subscriber.queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue

                record_agent = canonical_agent_id(
                    (record.get("query") or {}).get("agent_routed_to", "")
                )
                if selected_agent and record_agent != selected_agent:
                    continue
                payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                yield f"event: interaction\nid: {record.get('log_id', '')}\ndata: {payload}\n\n"
        finally:
            unsubscribe(subscriber)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{log_id}")
def export_log(log_id: str, _: None = Depends(require_log_api_key)):
    record = get_log_record(log_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Log record not found")
    return record
