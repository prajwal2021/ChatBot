"""The AI that keeps ServiceNow articles in line with the web pages linked to their category.

Two steps, so large categories stay affordable:
  1. triage: from the page change and a short preview of every article, pick the articles the change affects
     and say whether the change brings a topic no article covers yet;
  2. for each affected article, read it in full next to the page and propose the revised article (or its removal).
Nothing is applied here: the caller turns decisions into proposals that a person reviews.
"""
from __future__ import annotations

import json
import re
import time

import httpx

from .config import OPENAI_API_KEY, SN_MODEL

FORMAT = ("Article format, one item per line: '## ' or '### ' headings, plain sentences, '- ' bullets, '1. ' numbered steps, "
          "table rows as 'cell | cell', links as [text](url), images on their own line as ![alt](src).")
RULES = ("Rules: change only what the web page change makes wrong, outdated or incomplete. Keep everything else exactly as written, "
         "including wording, order, links and every image line. Never invent facts that are not on the page. Keep the article's voice. "
         "If the page change does not affect the article, the action is none.")
MAX_ARTICLE = 40000
MAX_PAGE = 30000


class AIError(Exception):
    pass


def enabled() -> bool:
    return bool(OPENAI_API_KEY)


def _chat(system: str, user: str, timeout: int = 180) -> dict:
    if not OPENAI_API_KEY:
        raise AIError("AI is off: add OPENAI_API_KEY to backend/.env.")
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=timeout,
                           headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                           json={"model": SN_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"OpenAI {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            last = e
            time.sleep(2 * (attempt + 1) ** 2)
    raise AIError(f"The AI did not answer ({type(last).__name__}: {last})")


def _diff_text(diff: list[dict]) -> str:
    return "\n".join(("+ " if d["t"] == "+" else "- " if d["t"] == "-" else "  ") + d["s"] for d in diff if d["t"] != "@")[:MAX_PAGE]


def triage(category: str, url: str, change: str, articles: list[dict], audit: bool) -> dict:
    """articles: [{id, title, content}]. Returns {"affected": [{id, why}], "new_topics": [{title, why}]}."""
    system = ("You maintain a university help-desk knowledge base (ServiceNow articles) for a chatbot. A web page is linked to the "
              f"category '{category}' because it is the source of truth for that category. "
              + ("You are given the whole page. Find the articles whose facts the page contradicts or updates (fees, dates, deadlines, "
                 "requirements, steps, contacts, names, links)."
                 if audit else
                 "The page just changed; you are given the lines added (+) and removed (-). Find the articles whose facts this change affects.")
              + " Only list an article when the page clearly affects it. List a new topic only when the page brings an important subject "
              "that no article covers AND that does not fit into any article you listed as affected (those will be updated with it); "
              "most changes need no new topic (at most 2).\n"
              'Respond with JSON: {"affected": [{"id": 0, "why": ""}], "new_topics": [{"title": "", "why": ""}]}')
    lines = [f"[{a['id']}] {a['title']}\n{(a['content'] or '')[:500]}" for a in articles]
    user = f"PAGE: {url}\n\n{'PAGE TEXT' if audit else 'PAGE CHANGE'}:\n{change[:MAX_PAGE]}\n\nARTICLES IN THIS CATEGORY:\n\n" + "\n\n".join(lines)
    out = _chat(system, user)
    ids = {a["id"] for a in articles}
    affected = [x for x in out.get("affected") or [] if isinstance(x, dict) and x.get("id") in ids][:10]
    topics = [x for x in out.get("new_topics") or [] if isinstance(x, dict) and (x.get("title") or "").strip()][:2]
    return {"affected": affected, "new_topics": topics}


def apply_edits(content: str, edits: list[dict]) -> str:
    """Apply find/replace edits; each `find` must match the article exactly once (spacing differences tolerated)."""
    out = content
    for e in edits:
        find, repl = (e.get("find") or ""), (e.get("replace") or "")
        if not find.strip():
            raise AIError("An edit did not say what to replace.")
        n = out.count(find)
        if n == 1:
            out = out.replace(find, repl)
            continue
        if n > 1:
            raise AIError(f"An edit matched {n} places: {find[:80]!r}")
        pat = re.escape(" ".join(find.split())).replace(r"\ ", r"\s+")       # tolerate spacing / line-break differences
        hits = list(re.finditer(pat, out))
        if len(hits) != 1:
            raise AIError(f"An edit did not match the article: {find[:80]!r}")
        out = out[:hits[0].start()] + repl + out[hits[0].end():]
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def revise(category: str, url: str, change: str, page_text: str, article: dict, audit: bool) -> dict:
    """Returns {"action": "update"|"remove"|"none", "reason", "title", "content"}. Updates are made as exact
    find/replace edits on the article, so text the AI did not touch (or did not see, for very long articles) is kept."""
    body = article["content"] or ""
    cut = len(body) > MAX_ARTICLE
    system = ("You keep one help-desk knowledge article (category '" + category + "') in line with its source web page. "
              + FORMAT + " " + RULES +
              " Make changes as edits: each edit has 'find' (text copied exactly from the article, long enough to be unique, "
              "usually a whole line) and 'replace' (the corrected text; empty to delete it). To add something, find the line it "
              "should follow and replace it with that line plus the new lines. Propose removal only when the page shows the whole "
              "article is obsolete (for example the program or service no longer exists). The reason is one or two plain sentences "
              "for a human reviewer naming the specific facts that changed.\n"
              'Respond with JSON: {"action": "update|remove|none", "reason": "", "new_title": "", "edits": [{"find": "", "replace": ""}]} '
              "(new_title only if the title itself must change).")
    user = (f"PAGE: {url}\n\n" + ("" if audit else f"WHAT CHANGED ON THE PAGE (+ added, - removed):\n{change[:MAX_PAGE]}\n\n")
            + f"THE PAGE NOW:\n{page_text[:MAX_PAGE]}\n\n"
            + f"ARTICLE TITLE: {article['title']}\nARTICLE" + (" (only the first part is shown; it continues)" if cut else "") + f":\n{body[:MAX_ARTICLE]}")
    out = _chat(system, user)
    action = out.get("action") if out.get("action") in ("update", "remove", "none") else "none"
    res = {"action": action, "reason": (out.get("reason") or "").strip()[:1500], "title": article["title"] or "", "content": ""}
    if action == "update":
        edits = [e for e in out.get("edits") or [] if isinstance(e, dict)]
        res["title"] = (out.get("new_title") or "").strip() or res["title"]
        res["content"] = apply_edits(body, edits) if edits else body
    return res


def write_new(category: str, url: str, page_text: str, topic: dict, existing: list[str]) -> dict | None:
    system = ("Write one new help-desk knowledge article for the category '" + category + "' from a university web page. "
              + FORMAT + " Use only facts on the page; copy figures, dates and links exactly. Write it the way the existing articles "
              "in the category are titled. If the page does not have enough to write a useful article, return an empty content.\n"
              'Respond with JSON: {"title": "", "content": "", "reason": ""}')
    user = (f"PAGE: {url}\n\nTOPIC: {topic.get('title')}\nWHY: {topic.get('why', '')}\n\nEXISTING ARTICLE TITLES:\n"
            + "\n".join(f"- {t}" for t in existing[:200]) + f"\n\nTHE PAGE:\n{page_text[:MAX_PAGE]}")
    out = _chat(system, user)
    if not (out.get("content") or "").strip() or not (out.get("title") or "").strip():
        return None
    return {"title": out["title"].strip()[:300], "content": out["content"].strip(),
            "reason": (out.get("reason") or topic.get("why") or "").strip()[:1500]}


def reconcile(category: str, url: str, diff: list[dict], page_text: str, articles: list[dict], audit: bool = False) -> list[dict]:
    """Returns decisions: [{action: update|remove|new|none, article_id?, title, content?, reason}]."""
    change = page_text if audit else _diff_text(diff)
    if not change.strip():
        return []
    small = len(articles) <= 4 and sum(len(a["content"] or "") for a in articles) < 30000
    tri = triage(category, url, change, articles, audit)
    if small:                                                 # few short articles: let the full read decide for each one
        tri["affected"] = [{"id": a["id"], "why": ""} for a in articles]
    by_id = {a["id"]: a for a in articles}
    out: list[dict] = []
    for x in tri["affected"]:
        a = by_id[x["id"]]
        try:
            r = revise(category, url, change, page_text, a, audit)
        except AIError as e:                                  # one bad answer must not lose the other articles' decisions
            out.append({"action": "none", "article_id": a["id"], "title": a["title"], "reason": f"Could not apply the AI's edit: {e}", "result": "failed"})
            continue
        if r["action"] == "update" and r["content"].strip() == (a["content"] or "").strip() and r["title"] == a["title"]:
            r["action"] = "none"
        out.append({**r, "article_id": a["id"], "title": r["title"] if r["action"] == "update" else a["title"],
                    "reason": r["reason"] or x.get("why", "")})
    for t in tri["new_topics"]:
        n = write_new(category, url, page_text, t, [a["title"] for a in articles])
        if n:
            out.append({"action": "new", **n})
    return out
