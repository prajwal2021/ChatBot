from __future__ import annotations

import asyncio
import difflib
import hashlib
import random
import json
import logging
import os
import re
import time
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path as _Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qdrant_client.models import FusionQuery, Fusion, Prefetch, SparseVector

from agents_config import AGENTS
from agent_ids import canonical_agent_id
from embeddings import embed, embed_batch, sparse_embed, sparse_embed_batch
from qdrant_store import get_client
from ingest import download_sharepoint, run_ingestion_from_bytes, ingest_to_collection  # noqa: F401
from llm import (
    generate_capability_details,
    generate_capability_topics,
    audit_answer,
    classify_crisis,
    generate_clarification,
    get_answer_models,
    resolve_intent,
    stream_answer,
)
from logger import log_answer_audit, log_interaction, log_error
from evaluator import (
    CRISIS_FALLBACK_PHRASES,
    CRISIS_STRONG_PHRASES,
    evaluate_response,
    is_crisis_query,
)
from cache import get_cached_response, store_cached_response
from session import get_history, add_turn, get_shown_chunks, add_shown_chunks
from ratelimit import is_rate_limited
from log_export import router as log_export_router
from trace_export import router as trace_export_router
from trace_emitter import build_trace, emit_trace

logger = logging.getLogger("kb_watcher")


def _is_low_info_query(text: str) -> bool:
    """Detect inputs that are too vague to retrieve reliably.

    Example: users typing "break" or "flag" (often spreadsheet markers) can
    otherwise retrieve arbitrary KB chunks and produce unrelated answers.
    """
    t = (text or "").strip().lower()
    if not t:
        return True

    # If the user clearly asked a question, let it through.
    if "?" in t:
        return False

    words = [w for w in t.split() if w]
    if len(words) >= 3:
        return False

    # Allow common interrogative starts even if short (e.g. "how enroll")
    interrogatives = {
        "what", "how", "when", "where", "who", "why",
        "can", "do", "does", "did",
        "is", "are", "was", "were",
        "should", "could", "would",
    }
    if words and words[0] in interrogatives:
        return False

    # Otherwise treat 1-2 word fragments as too ambiguous.
    return True


def _is_greeting_query(text: str) -> bool:
    """Recognize a standalone social greeting without sending it to retrieval."""
    normalized = re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()
    if not normalized:
        return False
    tokens = normalized.split()
    greeting_words = {"hello", "hi", "hey", "howdy", "greetings"}
    polite_words = {"there", "again", "everyone", "all", "good", "morning", "afternoon", "evening"}
    return len(tokens) <= 4 and any(token in greeting_words for token in tokens) and all(
        token in greeting_words or token in polite_words for token in tokens
    )


def _is_affirmation_query(text: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()
    return normalized in {
        "yes", "yes please", "yeah", "yep", "sure", "correct", "that one",
    }


def _numbered_reference_numbers(text: str) -> list[int]:
    """Return list indexes only when language indicates a prior-list reference."""
    lowered = (text or "").lower()
    # A bare index (or compact set of indexes) is inherently contextual. It is
    # only acted on later if the history actually contains those list items.
    bare_indexes = re.fullmatch(
        r"\s*#?\d{1,2}(?:\s*(?:,|&|and|also)\s*#?\d{1,2})*\s*",
        lowered,
    )
    if bare_indexes:
        return [int(value) for value in re.findall(r"\d{1,2}", lowered)]
    has_reference_language = bool(
        re.search(
            r"\b(?:point|points|item|items|number|numbers|option|options|step|steps)\b|"
            r"\b(?:talk\s*more|talk|explain|discuss|expand|cover|detail|details)\b",
            lowered,
        )
    )
    if not has_reference_language:
        return []
    return [int(value) for value in re.findall(r"(?<![\d.$])\b(\d{1,2})\b", lowered)]


def _is_context_reference_query(text: str) -> bool:
    """True when a message depends on an earlier turn for its meaning."""
    t = (text or "").strip().lower()
    if _is_affirmation_query(t) or _numbered_reference_numbers(t):
        return True
    reference_words = r"(?:point|points|item|items|number|numbers|option|options)"
    if re.search(rf"\b{reference_words}\s*(?:#\s*)?\d+", t):
        return True
    if re.search(r"\b(?:talk about|explain|discuss|cover|tell me about)\s+(?:#\s*)?\d+\b", t):
        return True
    return bool(
        re.search(
            r"\b(this|that|these|those|them|it|the previous one|the last one|"
            r"the above|more about|more information|more detail|more details|"
            r"in detail|elaborate|expand on|go deeper|continue)\b",
            t,
        )
    )


def _requests_exhaustive_answer(text: str) -> bool:
    """True when the user explicitly asks for the complete available answer."""
    t = (text or "").strip().lower()
    return bool(
        re.search(
            r"\b(all|everything|list all|show all|tell me all|every option|complete list)\b",
            t,
        )
    )


def _has_direct_information_signal(text: str) -> bool:
    """Detect a usable subject without hard-coding program-specific questions."""
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    generic = {
        "a", "about", "an", "and", "are", "can", "could", "do", "does",
        "cannot", "doesnt", "everything", "for", "help", "i", "information",
        "is", "issue", "it", "me", "more", "my", "need", "not", "of", "on",
        "or", "please", "problem", "question",
        "break", "flag", "hello", "hi", "hey", "yes", "yeah", "yep",
        "something", "stuff", "tell", "that", "the", "these", "thing", "this",
        "to", "want", "what", "when", "where", "which", "who", "why", "with",
        "work", "working", "would", "you",
    }
    meaningful = [token for token in tokens if len(token) >= 3 and token not in generic]
    return bool(meaningful)


def _list_items_from_assistant_message(
    content: str,
    *,
    allow_bullets: bool = True,
) -> dict[int, str]:
    """Extract the top-level numbered or bulleted list from an assistant turn."""
    numbered: dict[int, str] = {}
    bullets: list[tuple[int, str]] = []
    for line in (content or "").splitlines():
        # Accept plain and Markdown-emphasized lists, including
        # "**1. Heading**" and "1. **Heading**".
        numbered_match = re.match(
            r"^\s*(?:\*\*|__)?\s*(\d+)[.)]\s+(.+?)\s*(?:\*\*|__)?\s*$",
            line,
        )
        if numbered_match:
            item = re.sub(r"^(?:\*\*|__)|(?:\*\*|__)$", "", numbered_match.group(2).strip())
            numbered[int(numbered_match.group(1))] = item.strip()
            continue
        bullet_match = re.match(r"^(\s*)[-*•]\s+(.+?)\s*$", line)
        if bullet_match:
            bullets.append((len(bullet_match.group(1)), bullet_match.group(2)))

    if numbered:
        return numbered
    if not allow_bullets or not bullets:
        return {}

    min_indent = min(indent for indent, _ in bullets)
    top_level = [item for indent, item in bullets if indent == min_indent]
    return {i + 1: item for i, item in enumerate(top_level)}


def _resolve_history_list_reference(message: str, history: list[dict]) -> str | None:
    """Resolve requests like "point 2 and 3" against the latest assistant list."""
    normalized = re.sub(r"[^a-z0-9]+", " ", (message or "").lower()).strip()
    all_previous_items = normalized in {
        "all", "everything", "all of them", "list them all", "show me all",
        "tell me everything",
    }
    if not _is_context_reference_query(message) and not all_previous_items:
        return None

    numbers = _numbered_reference_numbers(message)
    lowered_message = (message or "").lower()
    asks_for_step = bool(re.search(r"\bsteps?\b", lowered_message))
    asks_for_point = bool(re.search(r"\b(?:points?|items?|options?)\b", lowered_message))

    if not numbers and not all_previous_items:
        return None

    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        content = turn.get("content", "")
        # Respect the label the assistant displayed. A later numbered block
        # explicitly introduced as steps must not hijack "point 2" from an
        # earlier topic/options list. Users can still request "step 2".
        procedural_list = bool(
            re.search(
                r"(?im)^(?:"
                r"#{1,4}\s+[^\n]{0,80}\b(?:steps?|procedure|instructions?)\b[^\n]*|"
                r"(?:\*\*|__)[^\n]{0,80}\b(?:steps?|procedure|instructions?)\b"
                r"[^\n]*(?:\*\*|__)"
                r")\s*$",
                content,
            )
        )
        if asks_for_point and procedural_list and not asks_for_step:
            continue
        # A numeric reference must resolve only against numbers the user
        # actually saw. Do not silently assign indexes to ordinary bullets.
        items = _list_items_from_assistant_message(
            content,
            allow_bullets=not bool(numbers),
        )
        if all_previous_items and items:
            return "Explain all of these topics: " + "; ".join(items.values())
        selected = [items[n] for n in numbers if n in items]
        if len(selected) == len(numbers):
            return "Explain these topics: " + "; ".join(selected)
    return None


def _latest_history_subject(history: list[dict]) -> str | None:
    """Return a concise subject from the most recent substantive exchange."""
    latest_user = ""
    latest_headings: list[str] = []
    for turn in reversed(history):
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if turn.get("role") == "assistant" and not latest_headings:
            # Preserve every top-level section from the most recent answer.
            # A follow-up asking for "more detail" after three selected topics
            # must not silently collapse to the first heading.
            for line in content.splitlines():
                stripped = line.strip()
                is_markdown_heading = bool(
                    re.match(r"^#{1,4}\s+\S", stripped)
                    or re.match(r"^(?:\*\*|__)[^*_].*(?:\*\*|__)$", stripped)
                )
                if not is_markdown_heading:
                    continue
                clean = re.sub(r"^#{1,4}\s+|^(?:\*\*|__)|(?:\*\*|__)$", "", stripped).strip()
                if 3 <= len(clean) <= 140 and clean not in latest_headings:
                    latest_headings.append(clean)
                if len(latest_headings) >= 6:
                    break
            if not latest_headings:
                first = next((line.strip() for line in content.splitlines() if line.strip()), "")
                clean = re.sub(r"^[#>*_\-\s]+|[*_\s]+$", "", first).strip()
                if 3 <= len(clean) <= 140:
                    latest_headings.append(clean)
        elif turn.get("role") == "user" and not latest_user:
            if _has_direct_information_signal(content):
                latest_user = content[:240]
        if latest_headings and latest_user:
            break

    parts = list(latest_headings)
    headings_text = "; ".join(latest_headings)
    if latest_user and latest_user.lower() not in headings_text.lower():
        parts.append(latest_user)
    return "; ".join(parts) or None


def _resolve_history_reference(message: str, history: list[dict]) -> str | None:
    """Create a standalone query for non-list pronoun/context follow-ups."""
    if not history:
        return None
    list_reference = _resolve_history_list_reference(message, history)
    if list_reference:
        return list_reference
    if not _is_context_reference_query(message):
        return None
    if _is_affirmation_query(message):
        latest_assistant = next(
            (
                (turn.get("content") or "").strip()
                for turn in reversed(history)
                if turn.get("role") == "assistant" and (turn.get("content") or "").strip()
            ),
            "",
        )
        # "Yes" is useful only when it answers the immediately preceding
        # assistant question and that question contains a concrete subject.
        # Never reach farther back and attach it to an unrelated old topic.
        if "?" in latest_assistant and _has_specific_information_subject(latest_assistant):
            return f"The user answered yes to this question: {latest_assistant}"
        return None
    subject = _latest_history_subject(history)
    if not subject:
        return None
    return f"Regarding {subject}: {message.strip()}"


_CONTEXT_PATTERNS = (
    r"\b(?:i am|i'm|we are|we're|we live|i live|my child|my son|my daughter|"
    r"i work|i have|we have|i already|we already)\b",
)


def _persistent_user_context(history: list[dict]) -> list[str]:
    """Extract durable user circumstances for retrieval and answer prioritization."""
    lines: list[str] = []
    seen: set[str] = set()
    for turn in history:
        if turn.get("role") != "user":
            continue
        content = re.sub(r"\s+", " ", (turn.get("content") or "").strip())
        if not content or not any(re.search(p, content, re.IGNORECASE) for p in _CONTEXT_PATTERNS):
            continue
        key = content.lower()
        if key not in seen:
            seen.add(key)
            lines.append(content[:300])
    return lines[-4:]


def _cross_agent_referral(agent_name: str, message: str) -> str | None:
    """Route explicit questions for another configured TTU assistant."""
    agent_name = canonical_agent_id(agent_name)
    current = AGENTS.get(agent_name, {})
    lowered = (message or "").lower()
    for other_name, cfg in AGENTS.items():
        if other_name == agent_name:
            continue
        terms = cfg.get("routing_terms", [])
        if not any(re.search(term, lowered, re.IGNORECASE) for term in terms):
            continue
        contact = cfg.get("contact", {})
        label = cfg.get("display_name", other_name)
        details = [contact.get("phone", ""), contact.get("email", ""), contact.get("url", "")]
        details = [value for value in details if value]
        suffix = f" You can contact them at {', '.join(details)}." if details else ""
        return f"That question is handled by {label}, rather than {current.get('display_name', agent_name)}.{suffix}"
    return None


def _matches_current_agent_scope(agent_name: str, message: str) -> bool:
    agent_name = canonical_agent_id(agent_name)
    lowered = (message or "").lower()
    cfg = AGENTS.get(agent_name, {})
    patterns = list(cfg.get("routing_terms", [])) + list(cfg.get("scope_terms", []))
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns)


# When false, the backend will not emit the UI image protocol (__IMAGES__) even if
# image_ids exist in Qdrant payloads.
KB_ENABLE_IMAGES = os.getenv("KB_ENABLE_IMAGES", "false").strip().lower() in {"1", "true", "yes", "y"}

# Stopgap alternative to RAG retrieval: dump the entire KB into the model's
# context instead of picking top-k chunks, while retrieval-completeness bugs
# (missed chunks, misattributed headings) get a permanent fix. Does not
# replace the RAG path — flip off to go back to it.
FULL_KB_CONTEXT_MODE = os.getenv("FULL_KB_CONTEXT_MODE", "false").strip().lower() in {"1", "true", "yes", "y"}
FULL_KB_CONTEXT_MODEL = os.getenv("FULL_KB_CONTEXT_MODEL", "gpt-4.1")
# Fraction of full-context answers re-checked by the verifier in the background,
# for logging only (logs/audit/answer_audit.jsonl). Each audit re-sends the whole
# KB to the verifier, so keep this low; 0 disables it.
FULL_KB_AUDIT_SAMPLE_RATE = float(os.getenv("FULL_KB_AUDIT_SAMPLE_RATE", "0.1"))

_background_tasks: set[asyncio.Task] = set()


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def _audit_full_kb_answer(
    agent_name: str,
    session_id: str,
    question: str,
    history: list[dict],
    draft: str,
    chunks: list[dict],
    guardrails: str,
) -> None:
    try:
        recent = [
            f"{t['role']}: {t['content'][:400]}" for t in history[-4:] if t.get("content")
        ]
        audit_question = question
        if recent:
            audit_question = "Conversation so far:\n" + "\n".join(recent) + f"\n\nCurrent question: {question}"
        verified = await audit_answer(audit_question, draft, chunks, guardrails)
        ratio = difflib.SequenceMatcher(None, _norm_ws(draft), _norm_ws(verified)).ratio()
        log_answer_audit({
            "agent": agent_name,
            "session_id": session_id,
            "question": question,
            "similarity": round(ratio, 3),
            "would_change": ratio < 0.9,
            "draft": draft,
            "verified": verified,
        })
    except Exception as exc:
        logger.warning("Answer audit failed: %s", exc)


# How many KB chunks to attach to a full-context trace as its evidence.
FULL_KB_TRACE_TOP_K = int(os.getenv("FULL_KB_TRACE_TOP_K", "12"))


async def _emit_full_kb_trace(
    *,
    agent_name: str,
    session_id: str,
    question: str,
    history: list[dict],
    answer: str,
    llm_latency_ms: int,
    total_latency_ms: int,
    guardrail_triggered: bool,
) -> None:
    """Emit the trace that AgentScope reads, for a full-KB-context answer.

    The full-context path hands the model the whole KB, so there is no retrieval
    step and therefore no retrieved chunks. The RAG path is the only place that
    emitted traces, so once full-context mode was switched on nothing reached
    AgentScope. The evaluation layers grade an answer against the chunks behind
    it, so we pick the KB chunks most relevant to the question after the answer
    has already been sent and attach those. This runs in the background and
    never delays or fails the reply. reconstructed_context marks that the
    chunks were chosen after the fact rather than being what the model saw.
    """
    try:
        query = question
        if len(question.split()) < 5:
            # A short follow-up ("and the cost?") has no meaning on its own.
            prior = next(
                (t["content"] for t in reversed(history)
                 if t.get("role") == "user" and t.get("content")),
                "",
            )
            if prior:
                query = f"{prior}. {question}"

        t0 = time.monotonic()
        results, _ = await asyncio.to_thread(
            _search_collection,
            AGENTS[agent_name]["collection"],
            query,
            FULL_KB_TRACE_TOP_K,
        )
        retrieval_result = {
            "method": "full_kb_context_evidence",
            "chunks_retrieved": len(results),
            "retrieval_latency_ms": int((time.monotonic() - t0) * 1000),
            "chunks": [
                {
                    "chunk_id": f"{r['source']}_{r['chunk_index']}",
                    "source": r["source"],
                    "text": r["text"],
                    "qdrant_score": r["score"],
                    "bm25_score": None,
                    "rank": i + 1,
                }
                for i, r in enumerate(results)
            ],
        }
        trace = build_trace(
            session_id=session_id,
            agent=agent_name,
            query_raw=question,
            retrieval_result=retrieval_result,
            response_text=answer,
            eval_result={},
            model_used=FULL_KB_CONTEXT_MODEL,
            llm_latency_ms=llm_latency_ms,
            total_latency_ms=total_latency_ms,
            fallback_triggered=False,
            is_llm_error=False,
            cache_hit=False,
            crisis_intercepted=False,
            guardrail_triggered=guardrail_triggered,
        )
        trace["reconstructed_context"] = True
        await emit_trace(trace)
    except Exception as exc:
        logger.warning("Full-KB trace emission failed: %s", exc)

# ── KB auto-sync (per-agent) ───────────────────────────────────────────────────

KB_POLL_MINUTES = int(os.getenv("KB_POLL_MINUTES", "30"))

# hash state per agent_id
_kb_hashes_path = _Path(__file__).parent / "logs" / "kb_hashes.json"
_kb_updates_path = _Path(__file__).parent / "logs" / "kb_last_updated.json"


def _load_kb_hashes() -> dict[str, str]:
    try:
        if _kb_hashes_path.exists():
            return json.loads(_kb_hashes_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_kb_hashes(hashes: dict[str, str]) -> None:
    try:
        _kb_hashes_path.parent.mkdir(parents=True, exist_ok=True)
        _kb_hashes_path.write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _load_kb_updates() -> dict[str, str]:
    try:
        if _kb_updates_path.exists():
            return json.loads(_kb_updates_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_kb_updates(updates: dict[str, str]) -> None:
    try:
        _kb_updates_path.parent.mkdir(parents=True, exist_ok=True)
        _kb_updates_path.write_text(json.dumps(updates, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _record_kb_update(agent_id: str) -> None:
    _kb_last_updated[agent_id] = datetime.now(timezone.utc).isoformat()
    _save_kb_updates(_kb_last_updated)


_kb_hashes: dict[str, str] = _load_kb_hashes()
_kb_last_updated: dict[str, str] = _load_kb_updates()

# Older deployments only persisted hashes. Use the hash file's modification time
# until each agent completes its next successful ingestion.
if _kb_hashes_path.exists():
    _legacy_updated_at = datetime.fromtimestamp(
        _kb_hashes_path.stat().st_mtime, tz=timezone.utc
    ).isoformat()
    for _agent_id in _kb_hashes:
        _kb_last_updated.setdefault(_agent_id, _legacy_updated_at)

_topic_menu_cache: dict[str, list[str]] = {}
_topic_detail_cache: dict[str, list[dict[str, object]]] = {}
_full_kb_cache: dict[str, list[dict]] = {}


def _full_kb_chunks(agent_name: str) -> list[dict]:
    """All chunks for an agent's collection, for the full-KB-context stopgap
    pipeline (FULL_KB_CONTEXT_MODE). Cached per agent; cleared on re-ingestion."""
    if agent_name in _full_kb_cache:
        return _full_kb_cache[agent_name]
    collection = AGENTS[agent_name]["collection"]
    client = get_client()
    chunks: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=256, with_payload=True, with_vectors=False, offset=offset,
        )
        for point in points:
            payload = point.payload or {}
            chunks.append({
                "text": payload.get("text", "") or "",
                "source": payload.get("source", "") or "",
                "chunk_index": int(payload.get("chunk_index", 0) or 0),
                "section": payload.get("section", "") or "",
                "score": 1.0,
                "image_ids": payload.get("image_ids", []) or [],
            })
        if offset is None:
            break
    _full_kb_cache[agent_name] = chunks
    return chunks


async def _check_agent(agent_id: str, cfg: dict) -> None:
    url = cfg.get("kb_url", "")
    if not url:
        return
    try:
        logger.info(f"KB watcher [{agent_id}]: checking...")
        data, filename = download_sharepoint(url)
        current_hash = hashlib.md5(data).hexdigest()
        if _kb_hashes.get(agent_id) == current_hash:
            logger.info(f"KB watcher [{agent_id}]: no change.")
            return
        logger.info(f"KB watcher [{agent_id}]: change detected in {filename}, re-ingesting...")
        count = run_ingestion_from_bytes(data, filename, cfg["collection"], full=True)
        _topic_menu_cache.pop(agent_id, None)
        _topic_detail_cache.pop(agent_id, None)
        _full_kb_cache.pop(agent_id, None)
        _kb_hashes[agent_id] = current_hash
        _save_kb_hashes(_kb_hashes)
        _record_kb_update(agent_id)
        logger.info(f"KB watcher [{agent_id}]: indexed {count} chunks into '{cfg['collection']}'")
    except Exception as e:
        logger.error(f"KB watcher [{agent_id}] error: {e}")


async def _check_all_agents() -> None:
    for agent_id, cfg in AGENTS.items():
        await _check_agent(agent_id, cfg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _check_all_agents()
    active = [k for k, v in AGENTS.items() if v.get("kb_url")]
    if active:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_check_all_agents, "interval", minutes=KB_POLL_MINUTES)
        scheduler.start()
        logger.info(f"KB watcher: polling every {KB_POLL_MINUTES} min for agents: {active}")
    yield


app = FastAPI(title="TTU KB API", lifespan=lifespan)

# Serve extracted images at /static/images/{id}
_static_dir = _Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
(_static_dir / "images").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_CORS_ORIGINS = [
    "http://localhost:3000",
    "https://tosmonline0002.ttu.edu",
]
_CORS_ORIGINS.extend(
    origin.strip()
    for origin in os.getenv("LOG_EXPORT_CORS_ORIGINS", "").split(",")
    if origin.strip()
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

app.include_router(trace_export_router)
app.include_router(log_export_router)


# ── Models ─────────────────────────────────────────────────────────────────────

class HistoryItem(BaseModel):
    role: str      # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    history: list[HistoryItem] = []


class IngestRequest(BaseModel):
    agent: str
    url: str


class FeedbackRequest(BaseModel):
    log_id: str
    log_date: str           # "YYYY-MM-DD" UTC
    feedback_type: str      # "thumbs_up" | "thumbs_down"
    feedback_text: str = ""


_ingest_status: dict = {"state": "idle", "detail": ""}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _chunk_key(source: str, chunk_index: int) -> str:
    # \x1f (unit separator) can't appear in a source filename, so this never
    # collides the way "_" or "::" could with a source name containing them.
    return f"{source}\x1f{chunk_index}"


def _search_collection(
    collection: str,
    message: str,
    top_k: int = 5,
    exclude_keys: set[tuple[str, int]] | None = None,
) -> tuple[list[dict], int]:
    """Hybrid dense+sparse search against a named collection.

    For multi-topic questions, we expand into a few sub-queries and merge results
    so retrieval covers all parts of the user request.

    exclude_keys lets a "give me more detail" follow-up prefer chunks that
    haven't already been shown in this conversation. Returns (chunks, total
    candidates found) — the gap between them tells the caller whether there
    was more relevant material than fit in top_k.
    """
    queries = _expand_queries(message)
    dense_vectors = embed_batch(queries) if len(queries) > 1 else [embed(message)]
    sparse_vectors = sparse_embed_batch(queries) if len(queries) > 1 else [sparse_embed(message)]
    client = get_client()

    per_query_k = max(5, top_k)
    merged: dict[tuple[str, int], dict] = {}
    ranked_by_query: list[list[dict]] = []

    for query_index, (dense_vector, sv) in enumerate(zip(dense_vectors, sparse_vectors)):
        response = client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=dense_vector, using="dense", limit=per_query_k * 2),
                Prefetch(
                    query=SparseVector(indices=sv[0], values=sv[1]),
                    using="sparse",
                    limit=per_query_k * 2,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=per_query_k,
            with_payload=True,
        )
        query_results: list[dict] = []
        for query_rank, r in enumerate(response.points):
            source = r.payload.get("source", "")
            chunk_index = int(r.payload.get("chunk_index", 0) or 0)
            key = (source, chunk_index)
            candidate = {
                "text": r.payload.get("text", ""),
                "source": source,
                "chunk_index": chunk_index,
                "section": r.payload.get("section", ""),
                "score": r.score,
                "image_ids": r.payload.get("image_ids", []),
                "query_index": query_index,
                "query_rank": query_rank,
            }
            query_results.append(candidate)
            prev = merged.get(key)
            if prev is None or candidate["score"] > prev["score"]:
                merged[key] = candidate
        query_text = queries[query_index].lower()
        if re.search(r"\b(cost|price|pricing|fee|how much)\b", query_text):
            query_results.sort(
                key=lambda item: (
                    not bool(re.search(r"\$\s*\d|\b(?:cost|fee|price)\b", item["text"], re.IGNORECASE)),
                    item["query_rank"],
                )
            )
        elif re.search(r"\b(duration|time limit|how long)\b", query_text):
            query_results.sort(
                key=lambda item: (
                    not bool(re.search(r"\b\d+\s*(?:days?|months?|weeks?|years?)\b", item["text"], re.IGNORECASE)),
                    item["query_rank"],
                )
            )
        ranked_by_query.append(query_results)

    # Reserve coverage for every sub-query before filling remaining slots by
    # score. This prevents one easy part of a multi-part question from crowding
    # all other requested parts out of the context window.
    exclude_keys = exclude_keys or set()
    minimum_per_query = max(1, min(3, top_k // max(1, len(ranked_by_query))))

    def _select(skip_excluded: bool) -> list[dict]:
        selected: list[dict] = []
        selected_keys: set[tuple[str, int]] = set()
        for query_results in ranked_by_query:
            added = 0
            for candidate in query_results:
                key = (candidate["source"], candidate["chunk_index"])
                if key in selected_keys or (skip_excluded and key in exclude_keys):
                    continue
                selected.append(candidate)
                selected_keys.add(key)
                added += 1
                if added >= minimum_per_query or len(selected) >= top_k:
                    break

        remaining = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        for candidate in remaining:
            if len(selected) >= top_k:
                break
            key = (candidate["source"], candidate["chunk_index"])
            if key in selected_keys or (skip_excluded and key in exclude_keys):
                continue
            selected.append(candidate)
            selected_keys.add(key)
        return selected

    selected = _select(skip_excluded=bool(exclude_keys))
    if not selected and merged:
        # Every relevant chunk was already shown earlier in the conversation —
        # repeating content is better than a false "no information" answer.
        selected = _select(skip_excluded=False)
    return selected, len(merged)


def _looks_multi_topic(message: str) -> bool:
    m = (message or "").lower()
    if m.count("?") >= 2:
        return True
    if any(sep in m for sep in ["; ", "\n", " and ", " also ", " plus ", " as well as "]):
        return len(m.split()) >= 10
    if len(re.findall(r"\b(?:what|how|when|where|who|which|whether|can|does|do|is|are)\b", m)) >= 2:
        return True
    return False


def _expand_queries(message: str) -> list[str]:
    raw = (message or "").strip()
    if not raw:
        return [""]

    if not _looks_multi_topic(raw):
        queries = [raw]
        if re.search(r"\b(?:fee|fees|cost|costs|price|pricing|tuition)\b", raw, re.IGNORECASE):
            queries.append(
                f"{raw} complete cost fee pricing amounts all types categories"
            )
        return queries

    enumerated_request = raw.count(",") >= 3
    if enumerated_request:
        parts = re.split(r"(?:\n+|;|,|\s+and\s+(?=(?:what|how|whether|the)\b))", raw, flags=re.IGNORECASE)
    else:
        # Split only at boundaries that introduce another question/aspect. A
        # plain "and" inside a program name or noun phrase is preserved.
        parts = re.split(
            r"(?:\n+|;|\?+|,\s*(?=(?:what|how|when|where|who|which|whether|can|does|do|is|are)\b)|"
            r"\s+and\s+(?=(?:what|how|when|where|who|which|whether|can|does|do|is|are)\b)|"
            r"\s+(?:also|plus)\s+)",
            raw,
            flags=re.IGNORECASE,
        )
    queries: list[str] = []
    seen: set[str] = set()
    anchor = ""
    for p in parts:
        p = (p or "").strip(" \t-:").strip()
        if len(p) < 6:
            continue
        if not anchor:
            anchor = p
            focused = p
        elif enumerated_request:
            focused = f"{raw}; Focus specifically on: {p}"
        else:
            # Retain the original subject so fragments such as "what score
            # passes" remain tied to the program/exam named in part one.
            focused = f"{anchor}; {p}"
        key = focused.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(focused)
        if len(queries) >= 8:
            break

    if len(queries) > 1 and raw.lower() not in seen:
        queries.insert(0, raw)

    # Add intent-preserving lexical variants for common conversational wording.
    # This helps sparse retrieval match tables/headings that say "fee" or
    # "duration" rather than the user's natural "how much/how long" phrasing.
    variants: list[str] = []
    contextual_subject = re.search(r"\bRegarding\s+(.+?)(?:;|:)", raw, re.IGNORECASE)
    concise_subject = ""
    if contextual_subject:
        concise_subject = contextual_subject.group(1).strip()
        concise_subject = re.sub(
            r"\b(?:overview|details|information)\b.*$",
            "",
            concise_subject,
            flags=re.IGNORECASE,
        ).strip(" :-")
        concise_subject = re.sub(r"\s*\([^)]{1,24}\)", "", concise_subject).strip()
        concise_subject = re.sub(r"\s+at\s+.+$", "", concise_subject, flags=re.IGNORECASE).strip()
        concise_subject = concise_subject or contextual_subject.group(1).strip()
    if contextual_subject and re.search(r"\bhow much\b", raw, re.IGNORECASE):
        variants.append(f"{concise_subject} pricing options all types")
    if contextual_subject and re.search(r"\bhow long\b", raw, re.IGNORECASE):
        variants.append(f"{concise_subject} duration time limit")
    for query in queries:
        variant = re.sub(
            r"\bhow much\b",
            "cost price fee pricing options all types",
            query,
            flags=re.IGNORECASE,
        )
        variant = re.sub(
            r"\bcosts?\b",
            "cost price fee pricing amounts",
            variant,
            flags=re.IGNORECASE,
        )
        variant = re.sub(r"\bhow long\b", "duration time limit", variant, flags=re.IGNORECASE)
        if variant.lower() != query.lower() and variant.lower() not in seen:
            variants.append(variant)
            seen.add(variant.lower())
    queries.extend(variants[:6])
    return queries or [raw]


def _is_topics_query(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", m).strip()
    direct_patterns = [
        r"\bwhat\s+can\s+you\s+(?:help|answer|do|cover)\b",
        r"\bwhat\s+(?:questions?|topics?|subjects?|areas?)\s+can\s+i\s+ask\b",
        r"\bwhat\s+do\s+you\s+cover\b",
        r"\bcapabilit(?:y|ies)\b",
        # Allow natural filler words: "all the topics", "main topics you
        # can help me with", and "topics you can answer about".
        r"\b(?:topics?|subjects?|areas?|sections?)\b.{0,45}\b(?:help|answer|cover|available)\b",
        r"\b(?:help|answer|cover)\b.{0,45}\b(?:topics?|subjects?|areas?|sections?)\b",
        r"\b(?:all|main|major|available)\b(?:\s+\w+){0,3}\s+(?:topics?|sections?)\b",
    ]
    return any(re.search(pattern, normalized) for pattern in direct_patterns)


def _is_topics_followup(message: str, history: list[dict]) -> bool:
    """Resolve an exhaustive follow-up to an earlier capability request.

    This deliberately requires a capability-related prior turn, so a generic
    "list all" after a tuition or program answer keeps its original subject.
    """
    if not _requests_exhaustive_answer(message):
        return False
    for turn in reversed(history[-6:]):
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if turn.get("role") == "assistant" and re.search(
            r"\bmajor\s+topics?\s+i\s+can\s+help\s+with\b",
            re.sub(r"[^a-z0-9]+", " ", content.lower()),
        ):
            return True
        if turn.get("role") == "user" and _is_topics_query(content):
            return True
    return False


def _is_topics_detail_followup(message: str, history: list[dict]) -> bool:
    """True when a user asks to expand a previously displayed topic menu."""
    normalized = re.sub(r"[^a-z0-9]+", " ", (message or "").lower()).strip()
    asks_for_detail = bool(
        re.search(
            r"\b(?:more\s+details?|more\s+detailed|bit\s+more\s+detailed|"
            r"expand|breakdown|subtopics?|what\s+(?:is|are)\s+inside|"
            r"what\s+(?:it|they)\s+(?:has|have|include)|inside\s+(?:it|them)|"
            r"as\s+points?)\b",
            normalized,
        )
    )
    if not asks_for_detail:
        return False

    for turn in reversed(history[-8:]):
        content = re.sub(
            r"[^a-z0-9]+",
            " ",
            (turn.get("content") or "").lower(),
        ).strip()
        if turn.get("role") == "assistant" and re.search(
            r"\bmajor\s+topics?\s+i\s+can\s+help\s+with\b",
            content,
        ):
            return True
    return False


def _has_specific_information_subject(message: str) -> bool:
    """Distinguish a concrete information request from a bot-coverage request.

    This vocabulary describes information types shared by the two assistants;
    it does not enumerate user phrasings. It safeguards semantic routing when a
    request contains words such as "answer" but is actually asking for data.
    """
    return bool(
        re.search(
            r"\b(?:programs?|degrees?|ph\.?d\.?|doctoral|doctorate|bachelors?|masters?|"
            r"admissions?|applications?|deadlines?|start dates?|calendar|tuition|fees?|"
            r"costs?|prices?|transfer credits?|prerequisites?|registration|financial aid|"
            r"certificates?|courses?|phone|telephone|email|contact|office hours?|"
            r"enrollment|exam|webcam|microphone|technical support|portal)\b",
            (message or "").lower(),
        )
    )


def _requested_topic_count(message: str, available: int) -> int:
    lowered = (message or "").lower()
    digit = re.search(r"\b(\d{1,2})\b", lowered)
    if digit:
        return max(1, min(int(digit.group(1)), available))
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    for word, count in words.items():
        if re.search(rf"\b{word}\b", lowered):
            return min(count, available)
    return available


def _extract_topic_candidates(text: str) -> str | None:
    if not text:
        return None
    first = (text.splitlines()[0] or "").strip()
    if not first:
        return None
    if len(first) > 100:
        return None
    lowered = first.lower()
    if lowered in {"question", "answer", "yes", "no", "meta"}:
        return None
    if lowered.startswith(("http://", "https://")):
        return None
    if first.endswith((".", "?", ",", ";", ":")):
        return None
    if first.startswith(("Step ", "- ", "• ")):
        return None
    return first


def _major_topics_for_agent(agent_name: str) -> list[str]:
    agent_name = canonical_agent_id(agent_name)
    if agent_name == "ttu-online":
        return [
            "Programs & degrees offered (undergrad/grad)",
            "Admissions requirements & application steps",
            "Application deadlines, start dates, and academic calendar",
            "Tuition/fees and tuition estimator guidance",
            "Transfer credits and prerequisites",
            "Registration: add/drop/withdrawal and common Raiderlink steps",
            "Financial aid basics and who to contact",
            "Industry Career Certificates",
            "Contact info, office hours, and support resources",
        ]
    if agent_name == "k12":
        return [
            "Full-time tuition-free, tuition-paid, and supplemental programs",
            "Elementary, middle, and high school options",
            "Admissions, eligibility, applications, and enrollment",
            "Courses, curriculum, pacing, extensions, and transfers",
            "Credit by Examination (CBE)",
            "Advanced Placement and dual credit",
            "Tuition, fees, payments, and refunds",
            "Grades, progress reports, and grade appeals",
            "Attendance, calendars, and state assessments",
            "Graduation, diplomas, and transcripts",
            "Focus, Parent, Counselor, and Canvas portals",
            "Exams, Proctorio, and technology requirements",
            "Accommodations and support for students with disabilities",
            "Textbooks, purchasing, and shipping",
            "Counselor, school, district, and institutional services",
            "Forms, contacts, and student support",
        ]
    return [
        "Answer questions that appear in the indexed documents",
        "Provide contact info and next steps when available",
    ]


def _indexed_topic_headings(agent_name: str) -> list[str]:
    cfg = AGENTS.get(agent_name, {})
    topics_by_source = _list_kb_topics(cfg.get("collection", ""), min_repeats=1)
    return [
        topic
        for source_topics in topics_by_source.values()
        for topic in source_topics
    ]


def _topic_heading_candidates(agent_name: str, topics: list[str]) -> dict[str, list[str]]:
    """Retrieve a small, relevant heading set for each capability category."""
    if not topics:
        return {}
    collection = AGENTS.get(agent_name, {}).get("collection", "")
    dense_vectors = embed_batch(topics)
    sparse_vectors = sparse_embed_batch(topics)
    client = get_client()
    candidates: dict[str, list[str]] = {}
    for topic, dense_vector, sparse_vector in zip(topics, dense_vectors, sparse_vectors):
        response = client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=dense_vector, using="dense", limit=24),
                Prefetch(
                    query=SparseVector(
                        indices=sparse_vector[0],
                        values=sparse_vector[1],
                    ),
                    using="sparse",
                    limit=24,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=12,
            with_payload=True,
        )
        topic_headings: list[str] = []
        seen: set[str] = set()
        for point in response.points:
            payload = point.payload or {}
            heading = (payload.get("section", "") or "").strip()
            if not heading:
                heading = _extract_topic_candidates(payload.get("text", "") or "") or ""
            key = heading.lower()
            if heading and key not in seen:
                seen.add(key)
                topic_headings.append(heading)
        candidates[topic] = topic_headings
    return candidates


async def _topics_for_agent(agent_name: str) -> list[str]:
    agent_name = canonical_agent_id(agent_name)
    topics = _topic_menu_cache.get(agent_name, [])
    if not topics:
        cfg = AGENTS.get(agent_name, {})
        try:
            headings = _indexed_topic_headings(agent_name)
            topics = await generate_capability_topics(
                headings,
                assistant_name=cfg.get("display_name", agent_name),
            )
        except Exception as exc:
            logger.warning("Could not build indexed topic menu for %s: %s", agent_name, exc)
        if topics:
            _topic_menu_cache[agent_name] = topics
        else:
            topics = _major_topics_for_agent(agent_name)
    return topics


async def _topic_response_for_agent(agent_name: str, message: str) -> str:
    topics = await _topics_for_agent(agent_name)
    topics = topics[:_requested_topic_count(message, len(topics))]
    return "**Major topics I can help with**\n\n" + "\n".join(
        f"{index}. {topic}" for index, topic in enumerate(topics, start=1)
    )


def _fallback_topic_details(topics: list[str], headings: list[str]) -> list[dict[str, object]]:
    """Derive a best-effort breakdown if semantic grouping is unavailable."""
    stopwords = {
        "a", "an", "and", "are", "for", "in", "of", "on", "or", "the",
        "to", "with", "information", "requirements", "services",
    }
    details: list[dict[str, object]] = []
    for topic in topics:
        topic_tokens = {
            token for token in re.findall(r"[a-z0-9]+", topic.lower())
            if len(token) >= 3 and token not in stopwords
        }
        ranked: list[tuple[int, str]] = []
        for heading in headings:
            heading_tokens = set(re.findall(r"[a-z0-9]+", heading.lower()))
            score = len(topic_tokens & heading_tokens)
            if score and heading.lower() != topic.lower():
                ranked.append((score, heading))
        ranked.sort(key=lambda item: (-item[0], len(item[1])))
        subtopics: list[str] = []
        seen: set[str] = set()
        for _, heading in ranked:
            key = heading.lower()
            if key in seen:
                continue
            seen.add(key)
            subtopics.append(heading.rstrip("?"))
            if len(subtopics) == 4:
                break
        if not subtopics:
            subtopics = [f"Questions and guidance related to {topic.lower()}"]
        details.append({"topic": topic, "subtopics": subtopics})
    return details


async def _topic_detail_response_for_agent(agent_name: str) -> str:
    agent_name = canonical_agent_id(agent_name)
    topics = await _topics_for_agent(agent_name)
    details = _topic_detail_cache.get(agent_name, [])
    if not details:
        headings: list[str] = []
        try:
            headings = _indexed_topic_headings(agent_name)
            candidates_by_topic = _topic_heading_candidates(agent_name, topics)
            details = await generate_capability_details(
                headings,
                topics,
                assistant_name=AGENTS.get(agent_name, {}).get("display_name", agent_name),
                candidates_by_topic=candidates_by_topic,
            )
        except Exception as exc:
            logger.warning("Could not build detailed topic menu for %s: %s", agent_name, exc)
        if not details:
            details = _fallback_topic_details(topics, headings)
        _topic_detail_cache[agent_name] = details

    lines = ["**Major topics and what they include**"]
    for index, item in enumerate(details, start=1):
        topic = str(item.get("topic", "")).strip()
        subtopics = item.get("subtopics", [])
        if not topic or not isinstance(subtopics, list):
            continue
        lines.extend(["", f"{index}. **{topic}**"])
        lines.extend(f"   - {subtopic}" for subtopic in subtopics if subtopic)
    lines.append("\nChoose a topic number or name when you want the full answer for that area.")
    return "\n".join(lines)


def _list_kb_topics(collection: str, min_repeats: int = 2) -> dict[str, list[str]]:
    """Return {source: [topics...]} derived from chunk-leading headings.

    We treat a "topic" as a chunk-leading heading that repeats across multiple
    chunks (via section heading stamping in ingestion). This filters out noise
    like single-line artifacts.
    """
    client = get_client()
    counts_by_source: dict[str, dict[str, int]] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=256,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        if not points:
            break
        for p in points:
            payload = p.payload or {}
            source = payload.get("source", "") or "unknown"
            text = payload.get("text", "") or ""
            section = (payload.get("section", "") or "").strip()
            topic = section if section else _extract_topic_candidates(text)
            if not topic:
                continue
            counts_by_source.setdefault(source, {})
            counts_by_source[source][topic] = counts_by_source[source].get(topic, 0) + 1
        if offset is None:
            break

    topics_by_source: dict[str, list[str]] = {}
    for source, counts in counts_by_source.items():
        topics = [t for t, n in counts.items() if n >= min_repeats]
        topics_by_source[source] = sorted(topics, key=lambda t: (-counts.get(t, 0), t.lower()))

    return {k: v for k, v in sorted(topics_by_source.items(), key=lambda kv: kv[0].lower())}


def _catalog_context(collection: str) -> dict | None:
    """Build compact, index-derived context for exhaustive program catalogs."""
    client = get_client()
    titles: list[str] = []
    seen: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=256,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        for point in points:
            payload = point.payload or {}
            candidates = [payload.get("section", "")]
            text = payload.get("text", "") or ""
            if text:
                candidates.append(text.splitlines()[0])
            for candidate in candidates:
                title = re.sub(r"\s+", " ", (candidate or "").strip())
                if not title or len(title) > 180:
                    continue
                if title.endswith("?"):
                    continue
                if not re.search(
                    r"\b(?:bachelor|master|doctor|degree|certificate)\b",
                    title,
                    re.IGNORECASE,
                ):
                    continue
                key = title.lower()
                if key not in seen:
                    seen.add(key)
                    titles.append(title)
        if offset is None:
            break
    if not titles:
        return None
    return {
        "text": "Available program and degree titles:\n" + "\n".join(f"- {title}" for title in titles),
        "source": "",
        "chunk_index": -1,
        "section": "Program catalog",
        "score": 1.0,
        "image_ids": [],
    }


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "kb_poll_minutes": KB_POLL_MINUTES,
        "agents": {
            k: {"url_configured": bool(v.get("kb_url")), "collection": v["collection"]}
            for k, v in AGENTS.items()
        },
    }


# ── Agents ─────────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents():
    return [
        {
            "id": k,
            "display_name": v["display_name"],
            "description": v["description"],
            "kb_last_updated": _kb_last_updated.get(k),
        }
        for k, v in AGENTS.items()
    ]


# ── Ingest (URL trigger) ───────────────────────────────────────────────────────

def _run_ingest_job(agent_id: str, url: str) -> None:
    global _ingest_status
    agent_id = canonical_agent_id(agent_id)
    if agent_id not in AGENTS:
        _ingest_status = {"state": "error", "detail": f"Unknown agent: {agent_id}"}
        return
    collection = AGENTS[agent_id]["collection"]
    try:
        _ingest_status = {"state": "running", "detail": f"[{agent_id}] Downloading..."}
        data, filename = download_sharepoint(url)
        _ingest_status = {"state": "running", "detail": f"[{agent_id}] Embedding {filename}..."}
        count = run_ingestion_from_bytes(data, filename, collection, full=True)
        _topic_menu_cache.pop(agent_id, None)
        _topic_detail_cache.pop(agent_id, None)
        _full_kb_cache.pop(agent_id, None)
        _record_kb_update(agent_id)
        _ingest_status = {"state": "done", "detail": f"[{agent_id}] Indexed {count} chunks from {filename}"}
    except Exception as e:
        _ingest_status = {"state": "error", "detail": str(e)}


@app.post("/ingest")
def ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    if _ingest_status.get("state") == "running":
        raise HTTPException(status_code=409, detail="Ingestion already in progress")
    background_tasks.add_task(_run_ingest_job, req.agent, req.url)
    return {"status": "started"}


@app.get("/ingest/status")
def ingest_status():
    return _ingest_status


# ── Feedback ───────────────────────────────────────────────────────────────────

@app.post("/feedback")
def feedback(req: FeedbackRequest):
    from logger import log_feedback
    ok = log_feedback(req.log_id, req.feedback_type, req.feedback_text or None, req.log_date)
    if not ok:
        raise HTTPException(status_code=404, detail="log_id not found for that date")
    return {"status": "updated"}


# ── Chat ───────────────────────────────────────────────────────────────────────

_NO_INFO_PHRASES = [
    "does not contain",
    "don't have that information",
    "do not have that information",
    "context does not",
    "not in the context",
    "no information",
    "cannot find",
    "not found in",
]


_CRISIS_RESPONSE = (
    "If you or someone you know is in crisis, please reach out for help immediately:\n\n"
    "• 911 — Emergency services\n"
    "• 988 Suicide & Crisis Lifeline — Call or text 988 (available 24/7)\n"
    "• Crisis Text Line — Text HOME to 741741\n"
    "• TTU Counseling Center — 806.742.3674\n\n"
    "You are not alone. Help is available right now.\n\n"
    "For questions about TTU programs, I'm here to assist."
)

def get_crisis_response(query: str) -> str | None:
    """Instant path for unambiguous self-harm phrases. Everything subtler is
    judged by the semantic classifier in the chat() wrapper."""
    lower = query.lower()
    if any(kw in lower for kw in CRISIS_STRONG_PHRASES):
        return _CRISIS_RESPONSE
    return None


_CRISIS_CHECK_TIMEOUT_S = 3.0


async def _crisis_check(message: str) -> bool:
    try:
        verdict = await asyncio.wait_for(classify_crisis(message), _CRISIS_CHECK_TIMEOUT_S)
    except Exception:
        verdict = None
    if verdict is None:
        lower = message.lower()
        return any(p in lower for p in CRISIS_FALLBACK_PHRASES)
    return verdict


@app.post("/chat/{agent_name}")
async def chat(agent_name: str, req: ChatRequest, request: Request):
    """Runs the normal pipeline while a small model checks, in parallel, whether
    the message is a genuine personal crisis. The response stream is held only
    until that check resolves (normally long before the first token), and is
    replaced by the crisis message if it flags one."""
    crisis_task = asyncio.create_task(_crisis_check(req.message))
    try:
        response = await _chat_impl(agent_name, req, request)
    except BaseException:
        crisis_task.cancel()
        raise
    if getattr(response, "handled_crisis", False):
        crisis_task.cancel()
        return response

    inner = response.body_iterator

    async def guarded():
        first = asyncio.ensure_future(inner.__anext__())
        try:
            is_crisis = await crisis_task
        except Exception:
            is_crisis = False
        if is_crisis:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            try:
                await inner.aclose()
            except Exception:
                pass
            yield _CRISIS_RESPONSE
            log_interaction(
                session_id=req.session_id or str(_uuid.uuid4()),
                query_text=req.message,
                agent=canonical_agent_id(agent_name),
                user_ip=request.client.host if request.client else "",
                user_agent=request.headers.get("user-agent", ""),
                retrieval_result={"method": "crisis_classifier", "chunks_retrieved": 0,
                                  "retrieval_latency_ms": 0, "chunks": []},
                response_result={"text": _CRISIS_RESPONSE, "model_used": "none",
                                 "source": "crisis_classifier"},
                eval_result=None,
            )
            return
        try:
            chunk = await first
        except StopAsyncIteration:
            return
        yield chunk
        async for chunk in inner:
            yield chunk

    response.body_iterator = guarded()
    return response


async def _chat_impl(agent_name: str, req: ChatRequest, request: Request):
    agent_name = canonical_agent_id(agent_name)
    if agent_name not in AGENTS:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found. Available: {list(AGENTS.keys())}",
        )

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    collection   = AGENTS[agent_name]["collection"]
    user_ip      = request.client.host if request.client else ""
    user_agent   = request.headers.get("user-agent", "")
    session_id   = req.session_id or str(_uuid.uuid4())
    t_request    = time.monotonic()
    user_ip_hash = hashlib.sha256(user_ip.encode()).hexdigest()

    def completed_text_response(
        text: str,
        *,
        source: str,
        fallback_triggered: bool = False,
        add_to_session: bool = True,
    ) -> StreamingResponse:
        """Stream and log a completed non-retrieval response consistently."""
        async def completed_stream():
            yield text
            if add_to_session:
                add_turn(session_id, req.message, text)
            log_interaction(
                session_id=session_id,
                query_text=req.message,
                agent=agent_name,
                user_ip=user_ip,
                user_agent=user_agent,
                retrieval_result={
                    "method": source,
                    "chunks_retrieved": 0,
                    "retrieval_latency_ms": 0,
                    "chunks": [],
                },
                response_result={
                    "text": text,
                    "model_used": "cached" if source == "cache" else "none",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "tokens_used": 0,
                    "llm_latency_ms": 0,
                    "total_latency_ms": int((time.monotonic() - t_request) * 1000),
                    "fallback_triggered": fallback_triggered,
                    "source": source,
                },
                eval_result=None,
            )

        return StreamingResponse(completed_stream(), media_type="text/plain; charset=utf-8")

    # POSITION 1 — rate limiting
    if is_rate_limited(user_ip_hash):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
        )

    # Crisis interception — bypass cache and session history
    crisis_msg = get_crisis_response(req.message)
    if crisis_msg:
        crisis_response = completed_text_response(crisis_msg, source="crisis", add_to_session=False)
        crisis_response.handled_crisis = True
        return crisis_response

    # Use the conversation history supplied by the frontend. Keep Redis as a
    # fallback for existing API clients that use a stable session_id.
    history_dicts = [turn.model_dump() for turn in req.history]
    if not history_dicts:
        session_turns = get_history(session_id)
        for turn in session_turns:
            history_dicts.append({"role": "user",      "content": turn["query"]})
            history_dicts.append({"role": "assistant",  "content": turn["response"]})

    # ── STOPGAP: full-KB-in-context pipeline (FULL_KB_CONTEXT_MODE) ─────────
    # Bypasses retrieval/intent routing entirely and hands the whole KB to the
    # model, so it isn't subject to top-k chunk selection or scope-keyword
    # guesses. Additive only — the RAG path below is untouched and resumes as
    # soon as the flag is off. No semantic-cache reuse across the two, since
    # a stale RAG-era (or full-context-era) cache hit shouldn't leak in when
    # the flag is flipped.
    if FULL_KB_CONTEXT_MODE:
        guardrails = AGENTS[agent_name].get("guardrails", "")
        full_chunks = _full_kb_chunks(agent_name)

        async def full_kb_streamer():
            full = ""
            t_llm = time.monotonic()
            async for chunk in stream_answer(
                req.message,
                full_chunks,
                guardrails=guardrails,
                history=history_dicts,
                models=[FULL_KB_CONTEXT_MODEL],
                verify=False,
                evidence_in_system=True,
            ):
                full += chunk
                yield chunk
            llm_latency_ms = int((time.monotonic() - t_llm) * 1000)

            is_llm_error = full.lower().startswith("error generating response")
            if not is_llm_error:
                add_turn(session_id, req.message, full)

            if (
                not is_llm_error
                and FULL_KB_AUDIT_SAMPLE_RATE > 0
                and random.random() < FULL_KB_AUDIT_SAMPLE_RATE
            ):
                task = asyncio.create_task(_audit_full_kb_answer(
                    agent_name, session_id, req.message, history_dicts,
                    full, full_chunks, guardrails,
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

            if not is_llm_error:
                trace_task = asyncio.create_task(_emit_full_kb_trace(
                    agent_name=agent_name,
                    session_id=session_id,
                    question=req.message,
                    history=history_dicts,
                    answer=full,
                    llm_latency_ms=llm_latency_ms,
                    total_latency_ms=int((time.monotonic() - t_request) * 1000),
                    guardrail_triggered=bool(guardrails),
                ))
                _background_tasks.add(trace_task)
                trace_task.add_done_callback(_background_tasks.discard)

            log_interaction(
                session_id=session_id,
                query_text=req.message,
                agent=agent_name,
                user_ip=user_ip,
                user_agent=user_agent,
                retrieval_result={
                    "method": "full_kb_context",
                    "chunks_retrieved": len(full_chunks),
                    "retrieval_latency_ms": 0,
                    "chunks": [],
                },
                response_result={
                    "text": full,
                    "model_used": FULL_KB_CONTEXT_MODEL,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "tokens_used": 0,
                    "llm_latency_ms": llm_latency_ms,
                    "total_latency_ms": int((time.monotonic() - t_request) * 1000),
                    "fallback_triggered": False,
                    "source": "full_kb_context",
                },
                eval_result=None,
            )

        return StreamingResponse(full_kb_streamer(), media_type="text/plain; charset=utf-8")

    # Social greetings are conversational turns, not knowledge-base searches.
    # Keeping them out of retrieval prevents arbitrary nearest chunks from
    # leaking into a welcome response.
    if _is_greeting_query(req.message):
        label = AGENTS[agent_name].get("display_name", agent_name)
        greeting_response = (
            f"Hello! I can help with questions about {label}, including programs, "
            "admissions, costs, courses, policies, and student support. What would you like to know?"
        )

        return completed_text_response(greeting_response, source="greeting")

    # Expand the previously displayed capability menu into subtopics. Handle
    # this before the general capability detector so "more detail about the
    # major topics" cannot collapse back into the same short menu.
    if _is_topics_detail_followup(req.message, history_dicts):
        detail_response = await _topic_detail_response_for_agent(agent_name)

        return completed_text_response(detail_response, source="topic_details")

    # "What topics can you cover?" — answer directly from the indexed
    # capability map so it cannot be rejected by probabilistic scope routing.
    # Also preserve that subject for follow-ups such as "give me a list of all".
    if _is_topics_query(req.message) or _is_topics_followup(req.message, history_dicts):
        topic_response = await _topic_response_for_agent(agent_name, req.message)

        return completed_text_response(topic_response, source="topics")

    guardrails = AGENTS[agent_name].get("guardrails", "")
    route_response = _cross_agent_referral(agent_name, req.message)
    if route_response:
        return completed_text_response(route_response, source="cross_agent_referral")

    reference_query = _resolve_history_reference(req.message, history_dicts)
    persistent_context = _persistent_user_context(history_dicts)

    if reference_query:
        intent = {
            "action": "context_reference",
            "rewritten_query": reference_query,
            "clarification_question": "",
            "error": "",
        }
    else:
        intent = await resolve_intent(
            req.message,
            guardrails=guardrails,
            history=history_dicts,
        )

    # Courtesy, acknowledgments, and other lightweight conversation should not
    # enter retrieval or inherit an unrelated intent from the previous answer.
    if intent["action"] == "social":
        social_response = intent.get("social_response", "").strip()
        if social_response:
            return completed_text_response(social_response, source="social")

    if intent["action"] == "unavailable":
        print(
            f"--- INTENT ANALYZER UNAVAILABLE: {intent.get('error', 'unknown')} "
            f"| history={len(history_dicts)}"
        )
        if _is_context_reference_query(req.message) or _is_low_info_query(req.message):
            clarification = await generate_clarification(
                req.message,
                guardrails=guardrails,
                history=history_dicts,
            )

            return completed_text_response(clarification, source="clarification")

        intent = {
            "action": "search_fallback",
            "rewritten_query": req.message,
            "clarification_question": "",
            "error": intent.get("error", ""),
        }

    # Semantic capability classification handles paraphrases that the fast
    # deterministic detector has never seen.
    if intent["action"] == "capabilities":
        # A semantic classifier can confuse "programs you answer questions
        # about" or "contact information" with a request for the chatbot's
        # general menu. Concrete information subjects always go to retrieval.
        # A message that names the agent's own subject directly (e.g. "what
        # is TTU Online?") must never fall through to the topics menu either.
        if _has_specific_information_subject(req.message) or _matches_current_agent_scope(
            agent_name, req.message
        ):
            intent = {
                "action": "search_broad",
                "rewritten_query": req.message,
                "clarification_question": "",
                "error": "",
            }
        else:
            topic_response = await _topic_response_for_agent(agent_name, req.message)

            return completed_text_response(topic_response, source="topics")

    if intent["action"] == "clarify":
        # A broad but identifiable subject should be answered from all available
        # KB evidence. Clarification is reserved for messages with no usable
        # subject, such as "I need help" or an unresolved contextual reference.
        if _requests_exhaustive_answer(req.message) or _has_direct_information_signal(req.message):
            intent = {
                "action": "search_broad",
                "rewritten_query": req.message,
                "clarification_question": "",
                "error": "",
            }
        else:
            clarification = intent["clarification_question"]

            return completed_text_response(clarification, source="clarification")

    if intent["action"] == "out_of_scope":
        # A semantic guess made without seeing the KB's actual content can
        # wrongly refuse real, answerable material — e.g. a newly added
        # section whose vocabulary was never anticipated by any keyword list.
        # Rather than trusting that guess (or hand-maintaining a per-agent
        # keyword list that has to be updated every time the KB grows), always
        # continue to retrieval and let the grounded LLM decide — it already
        # has explicit rules (SYSTEM_PROMPT + each agent's own guardrails) for
        # declining genuinely unrelated or sensitive topics using the real
        # evidence, not a guess made before retrieval even ran.
        intent = {
            "action": "search_broad",
            "rewritten_query": req.message,
            "clarification_question": "",
            "error": "",
        }

    retrieval_query = intent["rewritten_query"] or req.message
    if _looks_multi_topic(req.message) and intent["action"] != "context_reference":
        # Preserve the user's complete wording. Intent rewrites sometimes
        # compress enumerated requirements and make a requested aspect
        # invisible to query decomposition.
        retrieval_query = req.message
    answer_question = req.message
    if intent["action"] == "context_reference":
        answer_question = retrieval_query

    retrieval_query_with_context = retrieval_query
    if persistent_context:
        context_text = "; ".join(persistent_context)
        if context_text.lower() not in retrieval_query.lower():
            retrieval_query_with_context = f"{retrieval_query}. User context: {context_text}"
    print(
        f"--- INTENT: {intent['action']} | history={len(history_dicts)} "
        f"| rewritten={retrieval_query_with_context!r}"
    )

    # POSITION 2 — semantic response cache (agent-scoped)
    # Contextual follow-ups cannot safely share a response cached by message text
    # alone because the same phrase can refer to different prior answers.
    cached = get_cached_response(req.message, agent_id=agent_name) if not req.history else None
    if cached:
        print(f"  [CACHE HIT] sim={cached['similarity']} | {cached['original_query'][:60]}")
        return completed_text_response(cached["response"], source="cache")

    try:
        t0 = time.monotonic()
        base_k = 12
        if _requests_exhaustive_answer(req.message):
            base_k = 40
        elif (
            intent["action"] == "search_broad"
            or _looks_multi_topic(req.message)
            or _looks_multi_topic(retrieval_query_with_context)
        ):
            base_k = 25

        # On a "give me more detail" style follow-up, prefer chunks that
        # haven't already been shown in this conversation over repeating them.
        exclude_keys: set[tuple[str, int]] | None = None
        if reference_query:
            shown_raw = get_shown_chunks(session_id)
            if shown_raw:
                exclude_keys = set()
                for raw in shown_raw:
                    src, _, idx_str = raw.rpartition("\x1f")
                    if src and idx_str.isdigit():
                        exclude_keys.add((src, int(idx_str)))

        results, total_candidates = _search_collection(
            collection, retrieval_query_with_context, top_k=base_k, exclude_keys=exclude_keys
        )
        has_more_content = total_candidates > len(results)
        if (
            _requests_exhaustive_answer(req.message)
            and re.search(r"\b(?:programs?|degrees?|certificates?)\b", req.message, re.IGNORECASE)
        ):
            catalog = _catalog_context(collection)
            if catalog:
                results.insert(0, catalog)
        retrieval_latency_ms = int((time.monotonic() - t0) * 1000)
    except Exception as e:
        log_error(
            session_id, req.message, agent_name, user_ip, user_agent, e,
            error_type="qdrant_timeout", component="retrieval", severity="error",
        )
        raise HTTPException(status_code=503, detail=f"Retrieval error: {e}")

    print(f"\n--- [{agent_name}] QUERY: {req.message}")
    if retrieval_query_with_context != req.message:
        print(f"--- REWRITTEN QUERY: {retrieval_query_with_context}")
    print(f"--- CHUNKS RETRIEVED: {len(results)} ({retrieval_latency_ms}ms)")
    for i, r in enumerate(results):
        print(f"  [{i+1}] score={r['score']:.3f} | {r['text'][:80]}...")

    retrieval_result = {
        "method": "hybrid",
        "intent": {
            "action": intent["action"],
            "history_turns": len(history_dicts),
            "rewritten_query": retrieval_query_with_context,
            "analyzer_error": intent.get("error", ""),
        },
        "chunks_retrieved": len(results),
        "retrieval_latency_ms": retrieval_latency_ms,
        "chunks": [
            {
                "chunk_id": f"{r['source']}_{r['chunk_index']}",
                "source": r["source"],
                "text": r["text"],
                "qdrant_score": r["score"],
                "bm25_score": None,  # RRF fuses scores; individual BM25 not exposed by Qdrant
                "rank": i + 1,
            }
            for i, r in enumerate(results)
        ],
    }

    if not results:
        clarification = await generate_clarification(
            req.message,
            guardrails=guardrails,
            history=history_dicts,
        )

        return completed_text_response(clarification, source="clarification")

    # Collect unique image IDs from all retrieved chunks (preserve order)
    # Only used if KB_ENABLE_IMAGES is on.
    image_ids: list[str] = []
    if KB_ENABLE_IMAGES:
        seen: set[str] = set()
        for r in results:
            for img_id in r.get("image_ids", []):
                if img_id and img_id not in seen:
                    image_ids.append(img_id)
                    seen.add(img_id)

        if image_ids:
            print(f"--- IMAGES: {image_ids}")

    async def streamer():
        full = ""
        t_llm = time.monotonic()
        async for chunk in stream_answer(
            answer_question,
            results,
            guardrails=guardrails,
            history=history_dicts,
            user_context=persistent_context,
            has_more=has_more_content,
        ):
            full += chunk
            yield chunk
        llm_latency_ms   = int((time.monotonic() - t_llm) * 1000)
        total_latency_ms = int((time.monotonic() - t_request) * 1000)

        answered = not any(p in full.lower() for p in _NO_INFO_PHRASES)
        if KB_ENABLE_IMAGES and image_ids and answered:
            yield f"\n__IMAGES__:{','.join(image_ids)}"

        # POSITION 4 — store in cache and session (skip on LLM errors or 503)
        is_llm_error = full.lower().startswith("error generating response")
        if not is_llm_error:
            if not req.history:
                store_cached_response(req.message, full, agent_id=agent_name)
            add_turn(session_id, req.message, full)
            add_shown_chunks(
                session_id,
                [_chunk_key(r["source"], r["chunk_index"]) for r in results],
            )

        eval_result = evaluate_response(
            query=req.message,
            response_text=full,
            chunks=retrieval_result["chunks"],
            fallback_triggered=not answered,
        )
        if eval_result["recommendation"] != "ok":
            print(f"  [EVAL] {eval_result['recommendation'].upper()} | score={eval_result['score']} | flags={eval_result['triggered_flags']}")

        log_interaction(
            session_id=session_id,
            query_text=req.message,
            agent=agent_name,
            user_ip=user_ip,
            user_agent=user_agent,
            retrieval_result=retrieval_result,
            response_result={
                "text": full,
                "model_used": get_answer_models()[0],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "tokens_used": 0,
                "llm_latency_ms": llm_latency_ms,
                "total_latency_ms": total_latency_ms,
                "fallback_triggered": not answered,
                "source": "llm",
            },
            eval_result=eval_result,
        )

        # ── NLI trace emission ────────────────────────────
        if not is_llm_error:
            _trace = build_trace(
                session_id          = session_id,
                agent               = agent_name,
                query_raw           = req.message,
                retrieval_result    = retrieval_result,
                response_text       = full,
                eval_result         = eval_result,
                model_used          = get_answer_models()[0],  # TODO: stream_answer() doesn't surface which model in its fallback chain actually succeeded — using the primary model as a stand-in, same workaround log_interaction() already uses above.
                llm_latency_ms      = llm_latency_ms,
                total_latency_ms    = total_latency_ms,
                fallback_triggered  = not answered,
                is_llm_error        = is_llm_error,
                cache_hit           = False,
                crisis_intercepted  = False,
                guardrail_triggered = bool(guardrails),
            )
            asyncio.create_task(emit_trace(_trace))
        # ─────────────────────────────────────────────────

    return StreamingResponse(streamer(), media_type="text/plain; charset=utf-8")
