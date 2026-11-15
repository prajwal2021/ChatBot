"""Automatic verification of every page before its content is allowed into the review queue.

Runs on every crawl, but a page is only re-verified when its content changes. A page must:
  1. load (checked by the crawler: HTTP 200 and real HTML, no redirect off the site),
  2. not be an error page in disguise,
  3. contain real text (not empty, not a placeholder, not just a list of links),
  4. not be a copy of another page,
  5. (when an OpenAI key is set) be judged useful for the chatbot's audience by a model.
A person can overrule a failed check from the Pages screen ("Put back into crawling").
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx

from .config import CATEGORIZE_MODEL, OPENAI_API_KEY

SOFT_404 = re.compile(r"page (was )?not found|error 404|\b404\b.{0,30}(error|not found)|no longer (available|exists)|page (has|was) (been )?(moved|removed|deleted)|"
                      r"can.t find (the|that) page|does not exist", re.I)
PLACEHOLDER = re.compile(r"add main content|lorem ipsum|coming soon|under construction|content goes here|placeholder|test page|page content here", re.I)
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MIN_WORDS = 12        # below this a page cannot hold a usable fact; short pages above it are left to the AI check


def _check(name: str, ok: bool, note: str) -> dict:
    return {"name": name, "ok": ok, "note": note}


def basic_checks(data: dict, twin_url: str | None) -> list[dict]:
    """Deterministic checks. `twin_url` = another page in this crawl with identical content."""
    text = data["text"]
    plain = LINK.sub(r"\1", text)
    words = len(re.findall(r"[A-Za-z0-9$%']+", plain))
    link_chars = sum(len(m) for m in LINK.findall(text))
    body_chars = max(1, len(re.sub(r"(?m)^## .*$", "", plain)))
    out = [_check("Page loads", True, "Opened normally")]
    soft = words < 150 and bool(SOFT_404.search(data["title"] + "\n" + plain[:600]))
    out.append(_check("Not an error page", not soft, "The page loads but only says the content was not found" if soft else "Real page, not an error message"))
    placeholder = words < 120 and bool(PLACEHOLDER.search(plain))
    enough = words >= MIN_WORDS and not placeholder
    out.append(_check("Has real content", enough,
                      "Placeholder text, nothing written yet" if placeholder else f"Only {words} words of text" if not enough else f"{words:,} words of text"))
    farm = words < 400 and link_chars / body_chars > 0.7
    out.append(_check("More than a list of links", not farm, "Almost everything on the page is links to other pages" if farm else "Has its own text"))
    out.append(_check("Not a copy of another page", twin_url is None, f"Same content as {twin_url}" if twin_url else "Unique content"))
    return out


AI_SYSTEM = """You verify web pages for a university chatbot's knowledge base. Audience: {audience}
Decide whether the page contains information the chatbot could use to answer that audience's questions.

KEEP (useful=true): programs, courses, admissions, enrollment steps, costs, deadlines, policies, requirements, support
services, contacts, FAQs, how-to instructions, current staff or office contact details: anything with concrete facts.

REJECT (useful=false) when the page is:
- no_information: no concrete facts (a banner, a slogan, a thank-you/confirmation page, an image gallery, a form with no explanation)
- outdated: clearly about a past event, a past school year, an old announcement, an archived newsletter or old meeting minutes (today is {today})
- internal: meant for staff or developers, not the audience (templates, tracking, admin tools, internal training)
- test_or_placeholder: test content, dummy text, unfinished page
- error_page: an error or "not found" message

When unsure, keep the page: a human reviews the content afterwards.
Respond with JSON only: {{"useful": true, "kind": "useful|no_information|outdated|internal|test_or_placeholder|error_page", "reason": "<one short sentence, max 15 words>"}}"""

KIND_LABEL = {"no_information": "No useful information", "outdated": "Outdated", "internal": "Internal page",
              "test_or_placeholder": "Test or placeholder", "error_page": "Error page", "useful": "Useful"}


def _ai_one(audience: str, url: str, data: dict) -> dict | None:
    try:
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=35,
                       headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                       json={"model": CATEGORIZE_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": AI_SYSTEM.format(audience=audience, today=date.today().isoformat())},
                                          {"role": "user", "content": f"URL: {url}\nTITLE: {data['title']}\n\n{data['text'][:3500]}"}]})
        r.raise_for_status()
        j = json.loads(r.json()["choices"][0]["message"]["content"])
        kind = j.get("kind") if j.get("kind") in KIND_LABEL else ("useful" if j.get("useful") else "no_information")
        ok = bool(j.get("useful", True))
        reason = str(j.get("reason") or "").strip()[:200]
        return _check("Useful for the chatbot (AI check)", ok, reason if ok else f"{KIND_LABEL[kind]}: {reason}")
    except Exception:                                         # noqa: BLE001
        return None


def ai_checks(audience: str, pages: list[tuple[str, dict]], on_progress=None) -> dict[str, dict]:
    """{url: check} for the pages the model answered. Pages it could not judge are left out (and so kept)."""
    if not OPENAI_API_KEY or not pages:
        return {}
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, ((url, _), res) in enumerate(zip(pages, pool.map(lambda p: _ai_one(audience, p[0], p[1]), pages)), 1):
            if res:
                out[url] = res
            if on_progress:
                on_progress(i, len(pages), url)
    return out


def failed_reason(checks: list[dict]) -> str | None:
    bad = next((c for c in checks if not c["ok"]), None)
    return bad["note"] if bad else None
