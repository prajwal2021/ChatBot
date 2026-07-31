from __future__ import annotations

import asyncio
import json
import os
import re
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
_DEBUG = os.getenv("DEBUG", "false").lower() == "true"

def _parse_model_list(value: str) -> list[str]:
    return [m.strip() for m in (value or "").split(",") if m.strip()]


def get_fallback_models() -> list[str]:
    """Ordered list of models to try.

    Override with `OPENAI_CHAT_MODELS` as a comma-separated list.
    """
    env_models = os.getenv("OPENAI_CHAT_MODELS", "").strip()
    if env_models:
        return _parse_model_list(env_models)

    # Safe defaults: try GPT‑5.6 first, then fall back to older known-good models.
    return [
        "gpt-5.6",
        "gpt-5.6-terra",
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
    ]

SYSTEM_PROMPT = """You are a Texas Tech University assistant.
Follow the agent-specific scope rules below to help students and staff.

Answer ONLY using the provided context. If more detail from the user could lead
to a better knowledge-base search, ask one contextual clarification question.
Only when clarification would not help, say so honestly and direct the user to
the appropriate team named in the agent-specific scope rules.

RESPONSE FORMAT RULES:
1. Organize answers into clear sections with bold headers when the answer covers
   multiple topics or categories.

2. Use bullet points for any list of items (programs, steps, requirements, options).
   Never write a long paragraph when a bulleted list works better.

3. Always include relevant contact information when it appears in the context —
   phone numbers, email addresses, and links must be included in your response,
   not omitted.

4. End every response with a helpful next step — a relevant link, a contact,
   or an offer to help further.

5. Never repeat the same information twice in one response.

6. Be concise and well-organized. Prefer structured, scannable answers over
   dense walls of text.

7. When listing programs or degrees, group them by category (e.g. Business,
   Social Sciences, Computing) rather than one long flat list.

SAFETY RULES:
- If a user expresses thoughts of self-harm, suicide, or crisis, do not answer
  normally. Direct them to 988, 911, and the TTU counseling center immediately.
- Never provide medical, legal, or financial advice — route to the appropriate
  TTU office.
- Determine whether a question is within scope using the full conversation, not
  only the latest message. Resolve references such as "this," "that," "number 5,"
  and "more information" from earlier turns.
- Only give an out-of-scope response when the topic is genuinely unrelated to the
  agent's TTU program and cannot be understood from the conversation history.
- Never give an out-of-scope response when the user is referring to information
  from a previous assistant response.
- If the user's intent or the retrieved context is not specific enough to answer
  reliably, ask one short, natural clarification question instead of saying that
  the information is unavailable. Base the question on the conversation and the
  available context; do not invent TTU programs, policies, or services."""


# ── Markdown safety net ───────────────────────────────────────────────────────

def strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)           # bold
    text = re.sub(r'\*(.*?)\*', r'\1', text)                # italic
    text = re.sub(r'^\s*[\*\-]\s+', '', text, flags=re.MULTILINE)  # bullets
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE) # headers
    return text.strip()


# ── Prompt ────────────────────────────────────────────────────────────────────

def build_prompt(question: str, chunks: list[dict]) -> str:
    retrieved_context = "\n\n".join(c["text"] for c in chunks)
    return f"Context:\n{retrieved_context}\n\nQuestion: {question}"


def _debug_footer(chunks: list[dict]) -> str:
    lines = ["\n\n---\nDebug sources:"]
    for i, c in enumerate(chunks):
        lines.append(f"  Chunk {i + 1} | score={c['score']:.2f} | {c['source']}")
    return "\n".join(lines)


def _is_quota_error(e: Exception) -> bool:
    err = str(e)
    return "insufficient_quota" in err or "rate_limit" in err.lower() or "429" in err


def _is_model_fallback_error(e: Exception) -> bool:
    """Errors where we should try the next model slug."""
    status = getattr(e, "status_code", None)
    if status in {400, 401, 403, 404}:
        return True

    err = str(e).lower()
    return any(
        s in err
        for s in [
            "model",
            "does not exist",
            "not found",
            "no such model",
            "invalid model",
            "unsupported model",
            "you do not have access",
            "permission",
        ]
    )


# ── Intent resolution ─────────────────────────────────────────────────────────

_INTENT_SYSTEM_PROMPT = """You route messages for a retrieval-based university chatbot.
Decide whether the user's intent is clear enough to search the knowledge base.

Use the entire conversation to resolve short follow-ups and references. Do not
ask for clarification when a reasonable interpretation is available from prior
turns. If the intent is clear, rewrite it as a concise, standalone search query.

If there are multiple materially different interpretations, ask exactly one
short clarification question in friendly language suitable for parents and
students. You may include two to four brief choices when useful. Derive the
question from the conversation and agent scope; never invent specific programs,
policies, contacts, or services.

Return JSON only with these keys:
{"action":"search" or "clarify", "rewritten_query":"...", "clarification_question":"..."}
For search, clarification_question must be empty. For clarify, rewritten_query
may be empty."""


def _history_messages(history: list[dict] | None) -> list[dict]:
    messages: list[dict] = []
    for turn in history or []:
        role = "user" if turn.get("role") == "user" else "assistant"
        content = turn.get("content", "").strip()
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _parse_json_object(text: str) -> dict:
    cleaned = (text or "").strip()
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(cleaned[start:end + 1])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


async def resolve_intent(
    question: str,
    guardrails: str = "",
    history: list[dict] | None = None,
) -> dict[str, str]:
    """Return a dynamic clarify/search decision and a standalone retrieval query.

    On analyzer failure, continue with the original question so the main answer
    path remains available.
    """
    system = _INTENT_SYSTEM_PROMPT
    if guardrails:
        system += f"\n\nAgent scope:\n{guardrails}"

    messages = [{"role": "system", "content": system}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": question})

    for model_name in get_fallback_models():
        try:
            response = await _client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.1,
                max_completion_tokens=350,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content if response.choices else ""
            parsed = _parse_json_object(content or "")
            action = str(parsed.get("action", "")).strip().lower()
            rewritten = str(parsed.get("rewritten_query", "")).strip()
            clarification = str(parsed.get("clarification_question", "")).strip()

            if action == "clarify" and clarification:
                return {
                    "action": "clarify",
                    "rewritten_query": "",
                    "clarification_question": clarification,
                }
            if action == "search":
                return {
                    "action": "search",
                    "rewritten_query": rewritten or question,
                    "clarification_question": "",
                }
        except Exception as e:
            if _is_quota_error(e) or _is_model_fallback_error(e):
                continue
            break

    return {
        "action": "search",
        "rewritten_query": question,
        "clarification_question": "",
    }


async def generate_clarification(
    question: str,
    guardrails: str = "",
    history: list[dict] | None = None,
    chunks: list[dict] | None = None,
) -> str:
    """Generate one contextual clarification when retrieval cannot answer."""
    context = "\n\n".join(c.get("text", "") for c in (chunks or [])[:3] if c.get("text"))
    system = """Ask exactly one concise clarification question that will help a
parent or student restate their request for a university knowledge-base search.
Use the conversation, agent scope, and any candidate context. Do not answer the
request, list unsupported services, or say the information is unavailable."""
    if guardrails:
        system += f"\n\nAgent scope:\n{guardrails}"

    messages = [{"role": "system", "content": system}]
    messages.extend(_history_messages(history))
    prompt = f"User request: {question}"
    if context:
        prompt += f"\n\nClosest knowledge-base context:\n{context}"
    messages.append({"role": "user", "content": prompt})

    for model_name in get_fallback_models():
        try:
            response = await _client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=180,
            )
            content = response.choices[0].message.content if response.choices else ""
            clarification = (content or "").strip()
            if clarification:
                return clarification
        except Exception as e:
            if _is_quota_error(e) or _is_model_fallback_error(e):
                continue
            break

    return "Could you share a little more about what you are trying to do so I can point you to the right information?"


# ── Streaming ─────────────────────────────────────────────────────────────────

async def stream_answer(
    question: str,
    chunks: list[dict],
    guardrails: str = "",
    history: list[dict] | None = None,
):
    prompt = build_prompt(question, chunks)

    # System instruction = base prompt + per-agent guardrails (applied on every request)
    system_instr = SYSTEM_PROMPT
    if guardrails:
        system_instr += f"\n\nAgent scope rules:\n{guardrails}"

    # Build multi-turn messages — system, then history turns, then current prompt
    messages: list[dict] = [{"role": "system", "content": system_instr}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": prompt})

    for model_name in get_fallback_models():
        print(f"Trying model: {model_name} | max_completion_tokens=2048 | history={len(messages)-2} turns")
        try:
            full = ""
            stream = await _client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=2048,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    full += delta

            print(f"  [{model_name}] {full[:120]}...")

            # Stream word-by-word for natural UI feel
            words = full.split(" ")
            for i, word in enumerate(words):
                yield ("" if i == 0 else " ") + word
                await asyncio.sleep(0.02)

            if _DEBUG:
                yield _debug_footer(chunks)
            return

        except Exception as e:
            if _is_quota_error(e) or _is_model_fallback_error(e):
                print(f"  {model_name} failed ({type(e).__name__}), trying next...")
                continue
            else:
                yield f"Error generating response: {e}"
                return

    yield "All available models are rate-limited. Please try again in a few minutes."
