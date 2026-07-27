from __future__ import annotations

import hashlib
import json
import os
import re

import numpy as np
import redis

from embeddings import embed

REDIS_URL            = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL            = int(os.getenv("CACHE_TTL", 3600))

# Cache hit policy (tunable via env)
# - CACHE_SIMILARITY_THRESHOLD: minimum cosine similarity to consider a hit
# - CACHE_MIN_TOKEN_OVERLAP: minimum count of shared keywords between query and cached query
# - CACHE_MIN_SIM_GAP: require best_sim - second_best_sim >= gap to consider it "confident"
SIMILARITY_THRESHOLD = float(os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.95"))
MIN_TOKEN_OVERLAP    = int(os.getenv("CACHE_MIN_TOKEN_OVERLAP", "2"))
MIN_SIM_GAP          = float(os.getenv("CACHE_MIN_SIM_GAP", "0.01"))

r = redis.from_url(REDIS_URL, decode_responses=False)


def _cosine_similarity(a: list, b: list) -> float:
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "i", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "who", "will",
    "with", "you", "your",
}


def _keywords(text: str) -> set[str]:
    # Basic keyword extraction to prevent obvious mismatched cache hits.
    # (Not linguistic perfection; just a safety net.)
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOPWORDS}


def get_cached_response(query: str, *, agent_id: str | None = None) -> dict | None:
    """Return a cached response only when we are confident it's the same intent.

    Confidence signals:
    - cosine similarity above SIMILARITY_THRESHOLD
    - at least MIN_TOKEN_OVERLAP shared keywords
    - optional: best similarity must be separated from 2nd-best by MIN_SIM_GAP

    Also supports agent-scoped cache keys so different agents don't cross-contaminate.
    """
    query_vec = embed(query)
    query_kw = _keywords(query)

    prefix = f"cache:{agent_id or 'global'}:query:*"
    best: tuple[float, dict] | None = None
    second_best_sim: float = -1.0

    for key in r.scan_iter(prefix):
        try:
            raw = r.get(key)
            if not raw:
                continue
            data = json.loads(raw)   # json.loads accepts bytes (Python 3.6+)

            sim = _cosine_similarity(query_vec, data.get("vector", []))
            if sim < SIMILARITY_THRESHOLD:
                continue

            cached_query = data.get("query", "")
            overlap = len(query_kw & _keywords(cached_query))
            if overlap < MIN_TOKEN_OVERLAP:
                continue

            if best is None or sim > best[0]:
                if best is not None:
                    second_best_sim = max(second_best_sim, best[0])
                best = (sim, data)
            else:
                second_best_sim = max(second_best_sim, sim)

        except Exception:
            continue

    if not best:
        return None

    best_sim, best_data = best
    if second_best_sim >= 0 and (best_sim - second_best_sim) < MIN_SIM_GAP:
        # Not confident enough; too many similar cached entries.
        return None

    return {
        "response": best_data.get("response", ""),
        "cache_hit": True,
        "similarity": round(best_sim, 4),
        "original_query": best_data.get("query", ""),
    }


def store_cached_response(query: str, response: str, *, agent_id: str | None = None) -> None:
    query_vec = embed(query)
    key = f"cache:{agent_id or 'global'}:query:{hashlib.md5(query.encode()).hexdigest()}"
    r.setex(key, CACHE_TTL, json.dumps({
        "query": query,
        "vector": query_vec,
        "response": response,
    }))


def clear_cache() -> int:
    keys = list(r.scan_iter("cache:*:query:*"))
    if keys:
        return r.delete(*keys)
    return 0
