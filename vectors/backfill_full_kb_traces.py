"""Rebuild AgentScope traces for full-KB-context answers that were never traced.

While the full-KB-context branch did not emit traces, every answer it gave was
logged in logs/<date>.jsonl but never reached traces/<agent>/<date>.jsonl, so
AgentScope saw nothing. This rebuilds those traces from the interaction logs the
same way main._emit_full_kb_trace builds them going forward: the KB chunks most
relevant to the question are attached as the evidence, and the trace is marked
reconstructed_context.

Only answers logged with response.source == "full_kb_context" are rebuilt. Cache
hits, crisis replies and errors carry no evidence and were never traced. A
question that already has a trace (same agent, session and text) is skipped, so
the script can be re-run safely. Retrieval runs against the CURRENT knowledge
base, so the chunks are what the KB says now, not necessarily what it said then.

Run inside the chatbot container:
    python backfill_full_kb_traces.py --since 2026-09-12             # dry run
    python backfill_full_kb_traces.py --since 2026-09-12 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app")
sys.path.insert(0, str(ROOT))

LOGS = ROOT / "logs"
TRACES = ROOT / "traces"
MIN_WORDS_STANDALONE = 5


def _days(since: str, until: str) -> list[str]:
    return sorted(
        p.stem for p in LOGS.glob("????-??-??.jsonl") if since <= p.stem <= until
    )


def _existing_keys(agents: set[str], days: list[str]) -> set[tuple]:
    seen: set[tuple] = set()
    for agent in agents:
        for day in days:
            path = TRACES / agent / f"{day}.jsonl"
            if not path.exists():
                continue
            for line in path.open(encoding="utf-8", errors="ignore"):
                try:
                    t = json.loads(line)
                except Exception:
                    continue
                seen.add((agent, t.get("session_id"), (t.get("query") or {}).get("raw")))
    return seen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="first log day, YYYY-MM-DD")
    ap.add_argument("--until", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import main as app  # the retrieval code lives there; importing starts nothing

    days = _days(args.since, args.until)
    agents = set(app.AGENTS)
    existing = _existing_keys(agents, days)

    todo: list[dict] = []
    skipped: Counter = Counter()
    last_user: dict[str, str] = {}

    for day in days:
        for line in (LOGS / f"{day}.jsonl").open(encoding="utf-8", errors="ignore"):
            try:
                rec = json.loads(line)
            except Exception:
                skipped["unreadable line"] += 1
                continue
            q = rec.get("query") or {}
            resp = rec.get("response") or {}
            agent = app.canonical_agent_id(q.get("agent_routed_to") or "")
            question = (q.get("text") or "").strip()
            answer = resp.get("text") or ""
            session_id = rec.get("session_id") or ""

            if resp.get("source") != "full_kb_context":
                skipped[f"source={resp.get('source') or rec.get('retrieval', {}).get('method')}"] += 1
                continue
            if agent not in agents or not question:
                skipped["no agent/question"] += 1
                continue

            prior = last_user.get(session_id, "")
            last_user[session_id] = question

            if not answer.strip() or answer.lower().startswith("error generating response"):
                skipped["error/empty answer"] += 1
                continue
            if (agent, session_id, question) in existing:
                skipped["already traced"] += 1
                continue
            todo.append({
                "day": (rec.get("timestamp") or day)[:10],
                "ts": rec.get("timestamp"),
                "agent": agent,
                "session_id": session_id,
                "question": question,
                "prior": prior,
                "answer": answer,
                "llm_ms": int(resp.get("llm_latency_ms") or 0),
                "total_ms": int(resp.get("total_latency_ms") or 0),
            })

    by_day: dict = defaultdict(Counter)
    for t in todo:
        by_day[t["day"]][t["agent"]] += 1
    print(f"log days scanned: {days[0] if days else '-'} .. {days[-1] if days else '-'}")
    print(f"traces to rebuild: {len(todo)}")
    for d in sorted(by_day):
        print(f"  {d}  {dict(by_day[d])}")
    print("skipped:", dict(skipped))

    if not todo:
        return
    if not args.apply:
        print("\nDry run. Re-run with --apply to write the traces.")
        return

    written = failed = 0
    started = time.monotonic()
    for i, t in enumerate(todo, 1):
        try:
            query = t["question"]
            if len(query.split()) < MIN_WORDS_STANDALONE and t["prior"]:
                query = f"{t['prior']}. {query}"
            results, _ = app._search_collection(
                app.AGENTS[t["agent"]]["collection"], query, app.FULL_KB_TRACE_TOP_K
            )
            trace = app.build_trace(
                session_id=t["session_id"],
                agent=t["agent"],
                query_raw=t["question"],
                retrieval_result={
                    "method": "full_kb_context_evidence",
                    "chunks_retrieved": len(results),
                    "retrieval_latency_ms": 0,
                    "chunks": [
                        {
                            "chunk_id": f"{r['source']}_{r['chunk_index']}",
                            "source": r["source"],
                            "text": r["text"],
                            "qdrant_score": r["score"],
                            "bm25_score": None,
                            "rank": n + 1,
                        }
                        for n, r in enumerate(results)
                    ],
                },
                response_text=t["answer"],
                eval_result={},
                model_used=app.FULL_KB_CONTEXT_MODEL,
                llm_latency_ms=t["llm_ms"],
                total_latency_ms=t["total_ms"],
                fallback_triggered=False,
                is_llm_error=False,
                cache_hit=False,
                crisis_intercepted=False,
                guardrail_triggered=bool(app.AGENTS[t["agent"]].get("guardrails")),
            )
            trace["reconstructed_context"] = True
            if t["ts"]:
                trace["ts"] = t["ts"]
            out = TRACES / t["agent"] / f"{t['day']}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(trace, ensure_ascii=False) + "\n")
            written += 1
        except Exception as exc:
            failed += 1
            print(f"  failed {t['agent']} {t['session_id']}: {exc}")
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}  written={written} failed={failed}  {time.monotonic() - started:.0f}s")
    print(f"\ndone: written={written} failed={failed} in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
