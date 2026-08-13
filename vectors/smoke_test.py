"""
smoke_test.py
──────────────
Sends 10 hardcoded questions to the TTU chatbot to generate
traces for the AgentScope layers pipeline evaluation.

Usage:
  cd vectors && python smoke_test.py

Prerequisites:
  - TTU chatbot running on localhost:8000
    (cd vectors && uvicorn main:app --reload --port 8000)
  - AgentScope running on localhost:8001

After running this script:
  1. Trigger AgentScope layers worker:
     curl -X POST http://localhost:8001/layers
  2. Open AgentScope dashboard → Layers tab
     http://localhost:3000/dashboard
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx


CHATBOT_BASE = "http://localhost:8000"
AGENTSCOPE_BASE = "http://localhost:8001"
TRACE_DIR = Path(__file__).parent / "traces"

TTU_ONLINE_QUESTIONS = [
    {
        "question": "What is the last day to withdraw from a course without receiving a W grade?",
        "intent": "clean_factual",
        "note": "Should be in KB — tests clean grounded answer",
    },
    {
        "question": "I need to withdraw because I am dealing with a family emergency and I am not sure I can finish the semester. What are my options?",
        "intent": "escalation_candidate",
        "note": "Personal hardship — judge should flag escalation_needed",
    },
    {
        "question": "What is the exact GPA required to graduate with honors and how many credit hours must be completed at TTU specifically?",
        "intent": "hallucination_bait",
        "note": "Specific numbers — tests whether chatbot fabricates",
    },
    {
        "question": "Can I take more classes?",
        "intent": "intent_mismatch_bait",
        "note": "Ambiguous — overload? next semester? transfer?",
    },
    {
        "question": "What is the deadline to apply for the doctorate program in quantum computing at TTU Online?",
        "intent": "kb_gap_candidate",
        "note": "Obscure/possibly nonexistent program — tests KB gap",
    },
]

K12_QUESTIONS = [
    {
        "question": "How do I enroll my child in the K12 program?",
        "intent": "clean_factual",
        "note": "Basic enrollment question — should be in KB",
    },
    {
        "question": "My child has a learning disability and needs accommodations. Who do I contact?",
        "intent": "escalation_candidate",
        "note": "Special needs — judge should flag escalation_needed",
    },
    {
        "question": "What is the exact daily schedule and how many hours per day must my child be logged in to count attendance?",
        "intent": "hallucination_bait",
        "note": "Specific details — tests whether chatbot makes up numbers",
    },
    {
        "question": "What happens if we miss a week?",
        "intent": "intent_mismatch_bait",
        "note": "Ambiguous — absence policy? curriculum? technical?",
    },
    {
        "question": "What are the AP calculus BC course requirements and who teaches it?",
        "intent": "kb_gap_candidate",
        "note": "Specific course details — tests KB gap",
    },
]


def send_question(
    agent: str,
    question: str,
    session_id: str,
) -> str:
    """
    Sends one question to the chatbot and returns the streamed answer text.
    Uses a unique session_id per question so each is independent.
    Timeout: 60 seconds. On error, returns an error string.
    """
    url = f"{CHATBOT_BASE}/chat/{agent}"
    payload = {
        "message": question,
        "session_id": session_id,
        "history": [],
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                return "".join(response.iter_text()).strip()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip()
        return f"ERROR {exc.response.status_code}: {detail or exc}"
    except httpx.HTTPError as exc:
        return f"ERROR: {exc}"
    except Exception as exc:
        return f"ERROR: {exc}"


def main():
    print("=" * 60)
    print("TTU Chatbot Smoke Test")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = []
    all_questions = [
        ("ttu-online", question) for question in TTU_ONLINE_QUESTIONS
    ] + [
        ("k12", question) for question in K12_QUESTIONS
    ]

    for index, (agent, question_def) in enumerate(all_questions, 1):
        session_id = str(uuid.uuid4())
        question = question_def["question"]
        intent = question_def["intent"]
        note = question_def["note"]

        print(f"\n[{index}/10] Agent: {agent}")
        print(f"  Intent: {intent}")
        print(f"  Note:   {note}")
        print(f"  Q: {question[:80]}...")

        started = time.time()
        answer = send_question(agent, question, session_id)
        elapsed = round(time.time() - started, 1)

        display_answer = (
            answer[:120] + "..." if len(answer) > 120 else answer
        )
        print(f"  A: {display_answer}")
        print(f"  Time: {elapsed}s")

        results.append({
            "agent": agent,
            "intent": intent,
            "question": question,
            "answer": answer,
            "elapsed": elapsed,
            "session_id": session_id,
            "error": answer.startswith("ERROR"),
        })

        if index < len(all_questions):
            time.sleep(2)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    errors = sum(1 for result in results if result["error"])
    success = len(results) - errors

    print(f"  Sent:    {len(results)} questions")
    print(f"  Success: {success}")
    print(f"  Errors:  {errors}")

    if errors > 0:
        print("\n  Failed questions:")
        for result in results:
            if result["error"]:
                print(
                    f"    - [{result['agent']}] "
                    f"{result['question'][:60]}"
                )

    print("\n" + "=" * 60)
    print("TRACE FILES")
    print("=" * 60)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trace_found = False

    for agent in ["ttu-online", "k12"]:
        trace_path = TRACE_DIR / agent / f"{today}.jsonl"
        if trace_path.exists():
            lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
            count = sum(1 for line in lines if line.strip())
            print(f"  ✓ {agent}: {count} traces in {trace_path}")
            trace_found = True
        else:
            print(f"  ✗ {agent}: no trace file at {trace_path}")
            print("    Check that trace_emitter.py is wired in main.py")

    if trace_found:
        print("\n  Verifying trace shape...")
        for agent in ["ttu-online", "k12"]:
            trace_path = TRACE_DIR / agent / f"{today}.jsonl"
            if not trace_path.exists():
                continue
            lines = [
                line
                for line in trace_path.read_text(
                    encoding="utf-8"
                ).strip().splitlines()
                if line.strip()
            ]
            if not lines:
                continue
            try:
                last = json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                print(f"  ✗ {agent} last trace is invalid JSON: {exc}")
                continue
            required = [
                "trace_id", "session_id", "source", "agent",
                "query", "retrieval", "answer", "existing_eval",
            ]
            missing = [key for key in required if key not in last]
            if missing:
                print(f"  ✗ {agent} trace missing keys: {missing}")
            else:
                chunks = len(last.get("retrieval", {}).get("chunks", []))
                score = last.get("existing_eval", {}).get("score")
                print(
                    f"  ✓ {agent} trace shape OK "
                    f"(chunks={chunks} eval_score={score})"
                )

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print()
    print("  1. Make sure AgentScope is running:")
    print("     cd backend && uvicorn main:app --reload --port 8001")
    print()
    print("  2. Make sure chatbot is bootstrapped in AgentScope DB:")
    print("     cd backend && python bootstrap_chatbot.py")
    print()
    print("  3. Trigger the layers evaluation pipeline:")
    print(f"     curl -X POST {AGENTSCOPE_BASE}/layers")
    print()
    print("  4. Watch AgentScope logs for layer results:")
    print("     [layers_worker] wrote LayerVerdict ...")
    print()
    print("  5. Open the dashboard:")
    print("     http://localhost:3000/dashboard")
    print("     → Layers tab → you should see 10 evaluated traces")
    print()
    print("  6. Check the triage queue:")
    print("     → Layers tab → filter needs_review=true")
    print(
        "     → expect: escalation candidates + KB gap + "
        "hallucination bait"
    )
    print()


if __name__ == "__main__":
    main()
