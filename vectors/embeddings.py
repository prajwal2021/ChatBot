from __future__ import annotations

import os
import time

from fastembed import SparseTextEmbedding
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large").strip()
_EMBEDDING_DIMS_RAW = os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "").strip()
VECTOR_DIM = int(_EMBEDDING_DIMS_RAW) if _EMBEDDING_DIMS_RAW else 3072
_BATCH_SIZE = int(os.getenv("OPENAI_EMBEDDING_BATCH_SIZE", "96"))

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
SPARSE_MODEL_NAME = "Qdrant/bm25"

_sparse_model: SparseTextEmbedding | None = None


def get_sparse_model() -> SparseTextEmbedding:
    global _sparse_model
    if _sparse_model is None:
        print(f"Loading {SPARSE_MODEL_NAME} sparse encoder...")
        _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model


# ── Dense ──────────────────────────────────────────────────────────────────────

def _batches(items: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        return [items]
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def _embed_batch_openai(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    out: list[list[float]] = []
    kwargs: dict = {"model": EMBEDDING_MODEL, "input": texts}
    if _EMBEDDING_DIMS_RAW:
        kwargs["dimensions"] = VECTOR_DIM

    # Simple retry for transient rate limiting
    for attempt in range(6):
        try:
            resp = _client.embeddings.create(**kwargs)
            out.extend([d.embedding for d in resp.data])
            return out
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status == 429 and attempt < 5:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise


def embed(text: str) -> list[float]:
    return embed_batch([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for batch in _batches(texts, _BATCH_SIZE):
        vectors.extend(_embed_batch_openai(batch))
    return vectors


# ── Sparse (BM25) ──────────────────────────────────────────────────────────────

def sparse_embed(text: str) -> tuple[list[int], list[float]]:
    result = next(get_sparse_model().embed([text]))
    return result.indices.tolist(), result.values.tolist()


def sparse_embed_batch(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    results = list(get_sparse_model().embed(texts))
    return [(r.indices.tolist(), r.values.tolist()) for r in results]
