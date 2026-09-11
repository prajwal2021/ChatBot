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


def get_answer_models() -> list[str]:
    """Ordered, deployable answer models (override with OPENAI_CHAT_MODELS)."""
    env_models = os.getenv("OPENAI_CHAT_MODELS", "").strip()
    if env_models:
        return _parse_model_list(env_models)
    # These model IDs are supported by the configured OpenAI API. The previous
    # GPT-5.6 identifiers were not valid API model IDs and caused a 400 on every
    # request before silently falling back.
    return ["gpt-4o", "gpt-4o-mini"]


def get_utility_models() -> list[str]:
    """Smaller models for routing, clarification, and answer verification."""
    env_models = os.getenv("OPENAI_UTILITY_MODELS", "").strip()
    if env_models:
        return _parse_model_list(env_models)
    return ["gpt-4o-mini", "gpt-4o"]


def get_verifier_models() -> list[str]:
    env_models = os.getenv("OPENAI_VERIFIER_MODELS", "").strip()
    if env_models:
        return _parse_model_list(env_models)
    return ["gpt-4o", "gpt-4o-mini"]


# Backward-compatible name for any external imports.
def get_fallback_models() -> list[str]:
    return get_answer_models()

SYSTEM_PROMPT = """You are a Texas Tech University assistant.
Follow the agent-specific scope rules below to help students and staff.

Answer ONLY using the provided context. Answer immediately whenever the context
supports an answer. For broad questions, provide all relevant information in the
context instead of asking the user to narrow the request. Only ask one contextual
clarification when the request has no usable subject or the context cannot support
a reliable answer. If clarification would not help, direct the user to the
appropriate team named in the agent-specific scope rules.

RESPONSE FORMAT RULES:
1. Organize answers into clear sections with bold headers when the answer covers
   multiple topics or categories.

2. Use bullet points for any list of items (programs, steps, requirements, options).
   Never write a long paragraph when a bulleted list works better.

3. Include relevant contact information when it helps answer the request and appears in the context —
   phone numbers, email addresses, and links must be included in your response,
   not omitted.

4. Include a next step only when it is useful. Do not add an unrelated support
   referral to an out-of-scope response.

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
- Use relevant details the user shared anywhere in the conversation, including
  their location, role, and situation, to prioritize the most applicable parts
  of the answer while still providing everything they requested.
- Only give an out-of-scope response when the topic is genuinely unrelated to the
  agent's TTU program and cannot be understood from the conversation history.
- Never give an out-of-scope response when the user is referring to information
  from a previous assistant response.
- Ask a clarification question only when the conversation and retrieved context
  cannot support a useful answer. Base it on the conversation and available
  context; do not invent TTU programs, policies, or services.
- Treat every factual detail as untrusted until it is supported by the retrieved
  context. Do not fill gaps from general knowledge.
- Missing search evidence never proves that TTU does not offer a program or
  service. If the requested item is not established by the evidence, say you
  cannot confirm it from the official information available to you; do not make
  a categorical nonexistence claim.
- Answer every materially different part of a multi-part question. If one part
  is absent from the context, identify only that missing part without claiming
  the entire question is unanswered.
- Never mention knowledge-base filenames, document names, chunks, retrieval,
  source files, or phrases such as "when in the KB"."""


# ── Markdown safety net ───────────────────────────────────────────────────────

def strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)           # bold
    text = re.sub(r'\*(.*?)\*', r'\1', text)                # italic
    text = re.sub(r'^\s*[\*\-]\s+', '', text, flags=re.MULTILINE)  # bullets
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE) # headers
    return text.strip()


# ── Prompt ────────────────────────────────────────────────────────────────────

def build_prompt(
    question: str,
    chunks: list[dict],
    user_context: list[str] | None = None,
    has_more: bool = False,
) -> str:
    retrieved_context = "\n\n".join(
        f"Evidence {i} (section: {c.get('section') or 'unspecified'}):\n{c['text']}"
        for i, c in enumerate(chunks, start=1)
    )
    profile = ""
    if user_context:
        profile = "\n\nRelevant user context:\n- " + "\n- ".join(user_context)
    more_note = ""
    if has_more:
        more_note = (
            "\n\n[There is additional relevant information beyond what's shown above. "
            "End your answer by noting that more detail is available and invite the user "
            "to ask about a specific aspect. Do not mention documents, sections, chunks, "
            "or retrieval when doing this.]"
        )
    return (
        f"Retrieved evidence:\n{retrieved_context}{profile}{more_note}\n\n"
        f"Current request:\n{question}"
    )


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

Return social when the latest message is purely conversational, such as a
greeting, thanks, a polite acknowledgment, a farewell, or a question about how
the assistant is doing. A social message may follow a substantive answer; do
not repeat that answer or a capabilities menu merely because it appears in the
history. If the message also contains a substantive university question,
classify the substantive request instead. For social, write one brief, warm,
natural reply that offers further help when appropriate and makes no factual
claims about university programs.

Return capabilities when the user is asking what this assistant knows, what it
can answer, what kinds of help are available, or requests a menu/list of its
coverage. Classify by meaning rather than requiring particular words.
Do not return capabilities when the user requests concrete information such as
program or degree categories/examples, requirements, prices, or contact details;
those requests must use search.

Use the entire conversation to resolve short follow-ups and references. Do not
ask for clarification when a reasonable interpretation is available from prior
turns. If the intent is clear, rewrite it as a concise, standalone search query.

If there are multiple materially different interpretations, ask exactly one
short clarification question in friendly language suitable for parents and
students. You may include two to four brief choices when useful. Derive the
question from the conversation and agent scope; never invent specific programs,
policies, contacts, or services.

If the request is clearly unrelated to the agent scope and is not a reference to
the conversation, return out_of_scope. Do not classify vague or contextual
follow-ups as out_of_scope.

Return JSON only with these keys:
{"action":"search | clarify | capabilities | social | out_of_scope", "rewritten_query":"...", "clarification_question":"...", "social_response":"..."}
For search, clarification_question must be empty. For clarify, rewritten_query
may be empty. For social, social_response must contain the reply. For
capabilities or out_of_scope, all text fields must be empty."""


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

    analyzer_error = "invalid_response"
    for model_name in get_utility_models():
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
            social_response = str(parsed.get("social_response", "")).strip()

            if action == "clarify" and clarification:
                return {
                    "action": "clarify",
                    "rewritten_query": "",
                    "clarification_question": clarification,
                    "error": "",
                }
            if action == "search":
                return {
                    "action": "search",
                    "rewritten_query": rewritten or question,
                    "clarification_question": "",
                    "error": "",
                }
            if action == "out_of_scope":
                return {
                    "action": "out_of_scope",
                    "rewritten_query": "",
                    "clarification_question": "",
                    "error": "",
                }
            if action == "capabilities":
                return {
                    "action": "capabilities",
                    "rewritten_query": "",
                    "clarification_question": "",
                    "error": "",
                }
            if action == "social" and social_response:
                return {
                    "action": "social",
                    "rewritten_query": "",
                    "clarification_question": "",
                    "social_response": social_response,
                    "error": "",
                }
            analyzer_error = "invalid_response"
        except Exception as e:
            analyzer_error = type(e).__name__
            if _is_quota_error(e) or _is_model_fallback_error(e):
                continue
            break

    return {
        "action": "unavailable",
        "rewritten_query": "",
        "clarification_question": "",
        "error": analyzer_error,
    }


async def generate_capability_topics(
    headings: list[str],
    *,
    assistant_name: str,
) -> list[str]:
    """Group indexed document headings into a user-facing capability menu."""
    if not headings:
        return []

    unique: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for heading in headings:
        clean = re.sub(r"\s+", " ", (heading or "").strip())
        key = clean.lower()
        if not clean or key in seen:
            continue
        if total_chars + len(clean) > 24_000:
            break
        seen.add(key)
        unique.append(clean)
        total_chars += len(clean)

    system = f"""Create a capability menu for the {assistant_name} assistant from
document headings taken directly from its current knowledge-base index.

Group the headings into 10 to 16 distinct, high-level topics that a parent,
student, or counselor would recognize. Cover the breadth of the headings, merge
duplicates, and omit document artifacts, addresses, names, and overly narrow
questions. Use concise noun phrases. Do not add a topic unless at least one
heading supports it. Return JSON only as {{"topics":["...", "..."]}}."""

    for model_name in get_utility_models():
        try:
            response = await _client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": "Indexed headings:\n- " + "\n- ".join(unique)},
                ],
                temperature=0.1,
                max_completion_tokens=700,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content if response.choices else ""
            parsed = _parse_json_object(content or "")
            topics = parsed.get("topics", [])
            if not isinstance(topics, list):
                continue
            cleaned = [
                re.sub(r"\s+", " ", topic).strip(" -")
                for topic in topics
                if isinstance(topic, str) and topic.strip()
            ]
            if len(cleaned) >= 6:
                return cleaned[:16]
        except Exception as e:
            if _is_quota_error(e) or _is_model_fallback_error(e):
                continue
            break
    return []


async def generate_capability_details(
    headings: list[str],
    topics: list[str],
    *,
    assistant_name: str,
    candidates_by_topic: dict[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    """Expand capability labels into supported subtopics, not factual answers."""
    if not headings or not topics:
        return []

    source_headings = headings
    if candidates_by_topic:
        source_headings = [
            heading
            for topic in topics
            for heading in candidates_by_topic.get(topic, [])
        ]

    unique: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for heading in source_headings:
        clean = re.sub(r"\s+", " ", (heading or "").strip())
        key = clean.lower()
        if not clean or key in seen:
            continue
        if total_chars + len(clean) > 24_000:
            break
        seen.add(key)
        unique.append(clean)
        total_chars += len(clean)

    system = f"""Expand a capability menu for the {assistant_name} assistant.
For every supplied major topic, select one to five candidate heading IDs showing
the kinds of questions covered inside it. Preserve the supplied topic labels
and order. Select only headings that are directly and obviously relevant to
that topic. Never pad a topic with a loosely related heading to reach a quota;
one strong heading is better than several weak ones. A heading may appear under
more than one topic when it is genuinely relevant.

This is a description of chatbot coverage, not an answer about a particular
program. Do not include factual values such as dates, prices, eligibility ages,
course counts, requirements, or policy claims. Do not select only a few topics.
Return JSON only in this form:
{{"topics":[{{"topic":"exact supplied label","heading_ids":[1,2,3]}}]}}.
Use only IDs listed for that specific topic; never write new subtopics."""

    heading_ids = {heading: index for index, heading in enumerate(unique, start=1)}
    allowed_ids_by_topic: dict[str, set[int]] = {}
    candidate_sections: list[str] = []
    for topic in topics:
        candidates = (
            candidates_by_topic.get(topic, [])
            if candidates_by_topic
            else unique
        )
        allowed_ids = {
            heading_ids[heading]
            for heading in candidates
            if heading in heading_ids
        }
        allowed_ids_by_topic[topic.lower()] = allowed_ids
        candidate_sections.append(
            f"{topic}:\n" + "\n".join(
                f"  {heading_id}. {unique[heading_id - 1]}"
                for heading_id in sorted(allowed_ids)
            )
        )
    user_prompt = "Candidate indexed headings by major topic:\n\n" + "\n\n".join(candidate_sections)

    for model_name in get_utility_models():
        try:
            response = await _client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_completion_tokens=1800,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content if response.choices else ""
            parsed = _parse_json_object(content or "")
            items = parsed.get("topics", [])
            if not isinstance(items, list):
                continue

            by_topic: dict[str, list[str]] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                topic = str(item.get("topic", "")).strip()
                selected_ids = item.get("heading_ids", [])
                if not topic or not isinstance(selected_ids, list):
                    continue
                subtopics: list[str] = []
                allowed_ids = allowed_ids_by_topic.get(topic.lower(), set())
                for heading_id in selected_ids:
                    if not isinstance(heading_id, int) or heading_id not in allowed_ids:
                        continue
                    heading = unique[heading_id - 1]
                    if heading not in subtopics:
                        subtopics.append(heading)
                if subtopics:
                    by_topic[topic.lower()] = subtopics[:5]

            ordered = [
                {"topic": topic, "subtopics": by_topic[topic.lower()]}
                for topic in topics
                if topic.lower() in by_topic
            ]
            if len(ordered) == len(topics):
                return ordered
        except Exception as e:
            if _is_quota_error(e) or _is_model_fallback_error(e):
                continue
            break
    return []


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

    for model_name in get_utility_models():
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


# ── Grounding and output validation ──────────────────────────────────────────

_GROUNDING_SYSTEM_PROMPT = """You are the final verifier for a university RAG
assistant. Return JSON with exactly one key: {"answer":"..."}.

Rewrite the draft only as needed so that:
- every factual claim, number, deadline, requirement, program detail, contact,
  and URL is directly supported by the supplied evidence or agent rules;
- every materially different part of the request is answered when evidence is
  available;
- durable user context is respected and used to prioritize relevant details;
- no adjacent but unrelated FAQ instructions are mixed into the answer;
- a requirement from one named degree or program is never generalized to all
  programs; general admissions answers must say requirements vary when the
  evidence says they vary;
- no knowledge-base filenames, document names, chunks, sources, retrieval
  mechanics, or phrases such as "provided context," "provided evidence," or
  "when in the KB" appear;
- unsupported specifics are removed rather than guessed;
- absence from retrieved evidence is not proof that TTU does not offer a
  program or service; replace unsupported categorical nonexistence claims with
  a clear statement that the available official information cannot confirm it;
- the result remains concise, helpful Markdown.

If the evidence supports only part of the request, answer that part and plainly
state which specific detail is unavailable. Do not replace an otherwise useful
answer with a generic refusal or unnecessary clarification."""


def _sanitize_output(answer: str, chunks: list[dict], guardrails: str) -> str:
    """Remove internal/source leakage and invalid or unsupported Markdown links."""
    clean = (answer or "").strip()
    clean = re.sub(r"(?i)\b(?:document|source)[-_ ]?\d*\.docx\b", "", clean)
    clean = re.sub(r"(?im)^.*\bdebug sources?:.*$", "", clean)
    clean = re.sub(r"(?i)\b(?:when|found|available) in (?:the )?(?:kb|knowledge base)\b", "", clean)
    clean = re.sub(r"(?i)\b(?:the )?provided (?:context|evidence)\b", "the available information", clean)
    clean = re.sub(
        r"(?i)\b(?:the )?available evidence\b",
        "the official information available to me",
        clean,
    )

    allowed_text = "\n".join(c.get("text", "") for c in chunks) + "\n" + guardrails

    def replace_link(match: re.Match) -> str:
        label = match.group(1).strip()
        target = match.group(2).strip()
        if target == "#" or not re.match(r"^(?:https?://|mailto:)", target, re.IGNORECASE):
            return label
        if target.lower() not in allowed_text.lower():
            return label
        return match.group(0)

    clean = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, clean)
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


async def _verify_answer(
    question: str,
    draft: str,
    chunks: list[dict],
    guardrails: str,
    user_context: list[str] | None,
) -> str:
    evidence = "\n\n".join(
        f"Evidence {i} (section: {c.get('section') or 'unspecified'}):\n{c.get('text', '')}"
        for i, c in enumerate(chunks, start=1)
    )
    profile = "\n".join(f"- {line}" for line in (user_context or [])) or "None supplied"
    verification_request = (
        f"Agent rules:\n{guardrails or 'None'}\n\n"
        f"User context:\n{profile}\n\n"
        f"Request:\n{question}\n\n"
        f"Evidence:\n{evidence}\n\n"
        f"Draft answer:\n{draft}"
    )
    messages = [
        {"role": "system", "content": _GROUNDING_SYSTEM_PROMPT},
        {"role": "user", "content": verification_request},
    ]
    for model_name in get_verifier_models():
        try:
            response = await _client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0,
                max_completion_tokens=2200,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content if response.choices else ""
            parsed = _parse_json_object(content or "")
            verified = str(parsed.get("answer", "")).strip()
            if verified:
                return _sanitize_output(verified, chunks, guardrails)
        except Exception as e:
            if _is_quota_error(e) or _is_model_fallback_error(e):
                continue
            break
    return _sanitize_output(draft, chunks, guardrails)


# ── Streaming ─────────────────────────────────────────────────────────────────

async def stream_answer(
    question: str,
    chunks: list[dict],
    guardrails: str = "",
    history: list[dict] | None = None,
    user_context: list[str] | None = None,
    has_more: bool = False,
    models: list[str] | None = None,
    verify: bool = True,
    evidence_in_system: bool = False,
):
    # System instruction = base prompt + per-agent guardrails (applied on every request)
    system_instr = SYSTEM_PROMPT
    if guardrails:
        system_instr += f"\n\nAgent scope rules:\n{guardrails}"

    if evidence_in_system:
        # Put the (large, identical-per-agent) evidence in the system message
        # instead of the per-request user message. OpenAI's automatic prompt
        # caching only matches an identical prefix from the very start of the
        # request — history varies by session, so evidence placed after it
        # (as build_prompt does) would never hit the cache. Evidence in the
        # system message stays a stable, cacheable prefix across every
        # request to this agent, history or not.
        retrieved_context = "\n\n".join(
            f"Evidence {i} (section: {c.get('section') or 'unspecified'}):\n{c['text']}"
            for i, c in enumerate(chunks, start=1)
        )
        system_instr += f"\n\nRetrieved evidence:\n{retrieved_context}"
        prompt = f"Current request:\n{question}"
        if user_context:
            prompt = "Relevant user context:\n- " + "\n- ".join(user_context) + f"\n\n{prompt}"
    else:
        prompt = build_prompt(question, chunks, user_context=user_context, has_more=has_more)

    # Build multi-turn messages — system, then history turns, then current prompt
    messages: list[dict] = [{"role": "system", "content": system_instr}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": prompt})

    for model_name in (models or get_answer_models()):
        print(f"Trying model: {model_name} | verify={verify} | max_completion_tokens=2048 | history={len(messages)-2} turns")
        try:
            if not verify:
                # Real token-level streaming, single model call. Trades away
                # the independent verify-and-correct pass (it can't run before
                # the user sees anything once tokens are streamed live) for
                # much lower time-to-first-token — used by the full-KB-context
                # pipeline, which already has the whole KB as evidence and
                # relies on the system prompt's own grounding rules instead.
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
                        yield delta

                if _DEBUG:
                    yield _debug_footer(chunks)
                return

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

            full = await _verify_answer(
                question,
                full,
                chunks,
                guardrails,
                user_context,
            )
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
