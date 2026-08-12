from __future__ import annotations

import json
import asyncio
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone
from typing import TypedDict, List

# Zero coupling to the rest of the repo — this map is duplicated here on
# purpose rather than imported from agents_config.
AGENT_COLLECTION_MAP = {
    "ttu-online": "ttu_kb",
    "k12":        "k12",
}

TRACE_DIR = Path(__file__).parent / "traces"
_KB_VERSION_FILE = Path(__file__).parent / "kb_version.txt"


class TraceChunk(TypedDict):
    chunk_id:    str    # f"{source}_{chunk_index}"
    text:        str    # NLI premise
    source:      str
    chunk_index: int
    score:       float  # RRF fusion score
    image_ids:   list


class ChatbotTrace(TypedDict):
    trace_id:    str
    session_id:  str
    ts:          str    # UTC ISO-8601
    source:      str    # always "ttu_chatbot"
    agent:       str    # "ttu-online" or "k12"

    kb_version:     str
    prompt_version: str  # "v1.0" hardcoded for now
    model:          str  # actual model used — passed in as param

    query: dict
    retrieval: dict
    answer: dict
    existing_eval: dict
    latency: dict

    reconstructed_context: bool  # always False


def _kb_version() -> str:
    try:
        with _KB_VERSION_FILE.open("r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line:
            return first_line
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _chunk_score(chunk: dict) -> float:
    # main.py's retrieval_result chunks carry "qdrant_score"; the raw
    # _search_collection() shape (and the smoke-test fixture) carries "score".
    return chunk.get("score", chunk.get("qdrant_score", 0.0)) or 0.0


def _chunk_index(chunk: dict) -> int:
    # main.py's retrieval_result chunks have no chunk_index field of their
    # own (it's baked into chunk_id) but do carry a 1-indexed "rank".
    return chunk.get("chunk_index", chunk.get("rank", 1) - 1)


def _chunk_id(chunk: dict) -> str:
    existing = chunk.get("chunk_id")
    if existing:
        return existing
    return f"{chunk.get('source', '')}_{_chunk_index(chunk)}"


def _to_trace_chunk(chunk: dict) -> TraceChunk:
    return {
        "chunk_id":    _chunk_id(chunk),
        "text":        chunk.get("text", ""),
        "source":      chunk.get("source", ""),
        "chunk_index": _chunk_index(chunk),
        "score":       _chunk_score(chunk),
        "image_ids":   chunk.get("image_ids", []),
    }


def build_trace(
    session_id:          str,
    agent:               str,
    query_raw:           str,
    retrieval_result:    dict,
    response_text:       str,
    eval_result:         dict,
    model_used:          str,    # actual model from llm.py fallback
    llm_latency_ms:      int,
    total_latency_ms:    int,
    fallback_triggered:  bool,
    is_llm_error:        bool,
    cache_hit:           bool = False,
    crisis_intercepted:  bool = False,
    guardrail_triggered: bool = False,
) -> ChatbotTrace:
    chunks = retrieval_result.get("chunks", []) or []
    trace_chunks: List[TraceChunk] = [_to_trace_chunk(c) for c in chunks]
    scores = [_chunk_score(c) for c in chunks] if chunks else [0.0]

    collection = AGENT_COLLECTION_MAP.get(agent, agent)

    return {
        "trace_id":   str(uuid4()),
        "session_id": session_id,
        "ts":         datetime.now(timezone.utc).isoformat(),
        "source":     "ttu_chatbot",
        "agent":      agent,

        "kb_version":     _kb_version(),
        "prompt_version": "v1.0",
        "model":          model_used,

        "query": {
            "raw":                 query_raw,
            "cache_hit":           cache_hit,
            "crisis_intercepted":  crisis_intercepted,
            "guardrail_triggered": guardrail_triggered,
        },

        "retrieval": {
            "collection":       collection,
            "chunks_retrieved": retrieval_result.get("chunks_retrieved", len(chunks)),
            "max_score":        max(scores),
            "min_score":        min(scores),
            "chunks":           trace_chunks,
        },

        "answer": {
            "text":               response_text,
            "fallback_triggered": fallback_triggered,
            "answered":           not fallback_triggered,
            "is_llm_error":       is_llm_error,
        },

        "existing_eval": {
            "score":           eval_result.get("score", 0.0),
            "recommendation":  eval_result.get("recommendation", ""),
            "triggered_flags": eval_result.get("triggered_flags", []),
        },

        "latency": {
            "llm_ms":   llm_latency_ms,
            "total_ms": total_latency_ms,
        },

        "reconstructed_context": False,
    }


async def emit_trace(trace: ChatbotTrace) -> None:
    try:
        agent_dir = TRACE_DIR / trace["agent"]
        agent_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = agent_dir / f"{date_str}.jsonl"

        # Same write pattern as logger.py: plain sync open(), not aiofiles.
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[trace_emitter] failed to write trace_id={trace['trace_id']} "
              f"agent={trace['agent']}: {e}")
        return
