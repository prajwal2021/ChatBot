"""ServiceNow curation: one-time import, links per category, AI proposals from page changes, review and publishing.

Article lifecycle mirrors website entries: an article waits as new (imported or proposed), approved text is the
live knowledge, and a later change or removal waits as a proposal on top of it until a person decides.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import publish, sn_ai
from .config import SN_INSTANCE, USER_AGENT
from .crawler import canon
from .db import SessionLocal
from .diffing import line_diff
from .extract import extract, norm
from .models import Activity, Chatbot, SnArticle, SnArticleEvent, SnCategory, SnLink, SnLinkEvent, SnVersion, now
from .sn_html import article_content

QUEUE = ("new", "changed", "removal")
LIVE = ("approved", "changed", "removal")
STATE_LABEL = {"draft": "Draft in ServiceNow", "review": "In review in ServiceNow",
               "pending_retirement": "Pending retirement in ServiceNow"}
EXPIRED = "Expired in ServiceNow"
NEWER = "Newer version in ServiceNow"
STATE_WORD = {"draft": "draft", "review": "in-review", "pending_retirement": "pending-retirement", "published": "published"}
SYSTEM_LABELS = {EXPIRED, NEWER, "AI update", "New from link", "AI suggests removing", *STATE_LABEL.values()}


class SnError(Exception):
    pass


def log(db: Session, a: SnArticle, action: str, actor: str = "system", **detail) -> None:
    db.add(SnArticleEvent(article_id=a.id, action=action, actor=actor, detail=detail))


def record(db: Session, bot_id: int, action: str, actor: str, summary: str, **detail) -> None:
    db.add(Activity(chatbot_id=bot_id, area="servicenow", action=action, actor=actor, summary=summary, detail=detail))


def has_proposal(a: SnArticle) -> bool:
    return a.status in ("new", "changed") or (a.status == "rejected" and a.content is None)


def clear_proposal(a: SnArticle) -> None:
    a.p_title = a.p_content = a.p_category_id = a.p_kind = a.p_reason = a.p_link_id = a.p_event_id = None
    a.p_labels, a.p_edited = [], False


def current_text(a: SnArticle) -> tuple[str, str]:
    """What the article says right now for the AI: a waiting proposal wins over the approved text."""
    if has_proposal(a) and a.p_content is not None:
        return a.p_title or "", a.p_content
    return a.title or "", a.content or ""


def kb_url(number: str | None) -> str | None:
    return f"{SN_INSTANCE}/kb_view.do?sysparm_article={number}" if number else None


# ── import ────────────────────────────────────────────────────────────────────

def _expired(valid_to: str | None) -> bool:
    if not valid_to:
        return False
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(valid_to[:10], fmt).date() < date.today()
        except ValueError:
            continue
    return False


def _version_rank(state: str | None, updated: str | None) -> tuple:
    """Which ServiceNow record of an article to keep: the published one, then the most recently updated."""
    return (state == "published", updated or "")


def _one_per_number(articles: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """ServiceNow keeps one record per article version (published v1, v2 in review...). Keep one record per KB
    number and return, per number, the newer unpublished version whose text differs (if any)."""
    groups: dict[str, list[dict]] = {}
    out: list[dict] = []
    for art in articles:
        if art.get("number"):
            groups.setdefault(art["number"], []).append(art)
        else:
            out.append(art)
    newer: dict[str, dict] = {}
    for number, rows in groups.items():
        rows.sort(key=lambda r: _version_rank(r.get("state"), r.get("updated")), reverse=True)
        base = rows[0]
        out.append(base)
        text = article_content(base, SN_INSTANCE + "/")
        later = [r for r in rows[1:] if (r.get("updated") or "") > (base.get("updated") or "")
                 and norm(article_content(r, SN_INSTANCE + "/")) != norm(text)]
        if later:
            newer[number] = max(later, key=lambda r: r.get("updated") or "")
    return out, newer


def merge_versions(db: Session, bot: Chatbot, actor: str = "system") -> dict:
    """Collapse articles that came in more than once (one row per ServiceNow version) into one per KB number.
    The published version stays. If a newer version says something different, its text becomes a proposal on the
    kept article, so a reviewer decides whether it goes live. The extra rows are deleted."""
    stats = {"numbers": 0, "removed": 0, "proposals": 0}
    rows = db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.number.is_not(None))).all()
    groups: dict[str, list[SnArticle]] = {}
    for a in rows:
        groups.setdefault(a.number, []).append(a)
    text = lambda a: (a.content if a.content is not None else a.p_content) or ""   # noqa: E731
    for number, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda a: (_version_rank(a.sn_state, a.sn_updated), a.status == "approved"), reverse=True)
        base, others = items[0], items[1:]
        diff = [o for o in others if norm(text(o)) != norm(text(base)) and (o.sn_updated or "") >= (base.sn_updated or "")]
        newer = max(diff, key=lambda o: o.sn_updated or "", default=None)
        if newer is not None:
            reason = (f"ServiceNow also has a newer {STATE_WORD.get(newer.sn_state, newer.sn_state)} version of {number} with "
                      "different text. Approve to use the newer text, or reject to keep the published text.")
            if base.status == "approved":
                base.status, base.detected_at = "changed", now()
                base.p_title, base.p_content = (newer.title or newer.p_title or base.title), text(newer)
                base.p_category_id, base.p_kind, base.p_reason = base.category_id, "update", reason
                base.p_labels = sorted(set(base.labels or []) | {NEWER})
                stats["proposals"] += 1
            elif has_proposal(base):
                base.p_labels = sorted(set(base.p_labels or []) | {NEWER})
                base.p_reason = base.p_reason or reason
        for o in others:
            db.execute(update(SnLink).where(SnLink.article_id == o.id).values(article_id=base.id))
            db.delete(o)
        log(db, base, "merged_versions", actor, number=number, removed=[o.id for o in others],
            newer_text=newer is not None)
        stats["numbers"] += 1
        stats["removed"] += len(others)
    if stats["numbers"]:
        record(db, bot.id, "merge_versions", actor, f"Merged {stats['numbers']} articles that were imported once per ServiceNow "
               f"version: {stats['removed']} extra copies removed, {stats['proposals']} newer texts waiting in Review", **stats)
    db.commit()
    return stats


def import_kb(db: Session, bot: Chatbot, kb: dict, actor: str) -> dict:
    """kb = {categories: [{sys_id, label, parent, active}], articles: [{sys_id, number, title, state, category, template,
    valid_to, updated, parts, text}]}. Safe to run again: existing categories are updated, articles that nobody has
    reviewed yet are refreshed, everything else is left alone."""
    stats = {"categories": 0, "articles_new": 0, "articles_refreshed": 0, "articles_kept": 0}
    cats = {c.sys_id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
    for c in kb.get("categories") or []:
        row = cats.get(c["sys_id"])
        if row is None:
            row = SnCategory(chatbot_id=bot.id, sys_id=c["sys_id"], name="", path="")
            db.add(row)
            cats[c["sys_id"]] = row
        row.name, row.active = norm(c.get("label") or "") or "Untitled", bool(c.get("active", True))
        stats["categories"] += 1
    db.flush()
    parents = {c["sys_id"]: c.get("parent") for c in kb.get("categories") or []}
    for sid, row in cats.items():
        p = parents.get(sid)
        row.parent_id = cats[p].id if p in cats else None
    by_id = {r.id: r for r in cats.values()}

    def path(r: SnCategory) -> str:
        bits, seen = [], set()
        while r and r.id not in seen:
            seen.add(r.id)
            bits.insert(0, r.name)
            r = by_id.get(r.parent_id)
        return " > ".join(bits)

    for r in cats.values():
        r.path = path(r)
    for i, r in enumerate(sorted(cats.values(), key=lambda r: r.path.lower())):
        r.position = i

    existing = {a.sys_id: a for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.sys_id.is_not(None)))}
    have_numbers = {a.number: a.sys_id for a in existing.values() if a.number}
    incoming, newer_of = _one_per_number(kb.get("articles") or [])
    stats["versions_skipped"] = len(kb.get("articles") or []) - len(incoming)
    for art in incoming:
        if art.get("number") in have_numbers and have_numbers[art["number"]] != art["sys_id"]:
            stats["versions_skipped"] += 1                    # another version of this article is already here
            continue
        content = article_content(art, SN_INSTANCE + "/")
        title = norm(art.get("title") or "") or art.get("number") or "Untitled article"
        cat = cats.get(art.get("category") or "")
        raw = " ".join(p[1] for p in art.get("parts") or [] if p[1]) + (art.get("text") or "")
        internal = "INTERNAL" in (art.get("title") or "") or "INTERNAL USE ONLY" in raw.upper()
        newer = newer_of.get(art.get("number") or "")
        labels = [x for x in [STATE_LABEL.get(art.get("state") or ""), EXPIRED if _expired(art.get("valid_to")) else None,
                              "Internal only" if internal else None, NEWER if newer else None] if x]
        a = existing.get(art["sys_id"])
        if a is not None and (a.reviewer or a.status != "new" or a.p_kind != "import" or a.p_edited):
            stats["articles_kept"] += 1                       # a person or the AI already worked on it: leave it alone
            continue
        if a is None:
            a = SnArticle(chatbot_id=bot.id, sys_id=art["sys_id"], status="new")
            db.add(a)
            stats["articles_new"] += 1
        else:
            stats["articles_refreshed"] += 1
        a.number, a.sn_state, a.sn_template = art.get("number"), art.get("state"), art.get("template")
        a.valid_to, a.sn_updated = art.get("valid_to"), art.get("updated")
        a.source_html = "\n".join(p[1] for p in art.get("parts") or [] if p[1]) or art.get("text") or ""
        a.sn_content = content
        a.category_id = cat.id if cat else None
        a.p_title, a.p_content, a.p_category_id, a.p_labels, a.p_kind = title, content or "(This article has no text in ServiceNow.)", a.category_id, labels, "import"
        a.p_reason = (f"ServiceNow also has a newer {STATE_WORD.get(newer.get('state'), newer.get('state'))} version of {a.number}. "
                      "This is the published text; check the newer one in ServiceNow before approving.") if newer else None
        db.flush()
        log(db, a, "imported", actor, number=a.number, state=a.sn_state)
    record(db, bot.id, "import", actor, f"Imported from ServiceNow: {stats['articles_new']} new articles, "
           f"{stats['articles_refreshed']} refreshed, {stats['categories']} categories", **stats)
    db.commit()
    return stats


# ── review ────────────────────────────────────────────────────────────────────

def edit(db: Session, a: SnArticle, actor: str, *, title=None, content=None, category_id=None, labels=None) -> None:
    if a.status in ("removal", "removed"):
        raise SnError("This article is being removed and cannot be edited. Reject the removal first to keep it.")
    if category_id and not db.scalar(select(SnCategory.id).where(SnCategory.id == category_id, SnCategory.chatbot_id == a.chatbot_id)):
        raise SnError("That category does not exist.")
    if title is not None and not norm(title):
        raise SnError("The title cannot be empty.")
    if content is not None and not norm(content):
        raise SnError("The content cannot be empty.")
    prop = has_proposal(a)
    pre = "p_" if prop else ""
    before = {"title": getattr(a, pre + "title"), "content": getattr(a, pre + "content")}
    changed = (title is not None and title.strip() != before["title"]) or (content is not None and content.strip() != before["content"])
    if title is not None:
        setattr(a, pre + "title", title.strip())
    if content is not None:
        setattr(a, pre + "content", "\n".join(x.rstrip() for x in content.strip().splitlines()))
    if category_id is not None:
        setattr(a, pre + "category_id", category_id or None)
    if labels is not None:
        setattr(a, pre + "labels", [x for x in dict.fromkeys(norm(l)[:40] for l in labels) if x][:8])
    if prop:
        a.p_edited = a.p_edited or changed
    else:
        a.revision += 1
        a.reviewer, a.reviewed_at = actor, now()
    log(db, a, "edited", actor, text_changed=changed, **(before if changed else {}))


def approve(db: Session, a: SnArticle, actor: str) -> None:
    if a.status == "removal":
        a.status, a.reviewer, a.reviewed_at = "removed", actor, now()
        clear_proposal(a)
        log(db, a, "removal_approved", actor)
        return
    if not has_proposal(a) or a.p_content is None:
        raise SnError("There is nothing waiting for approval on this article.")
    kind = "change_approved" if a.content is not None else "approved"
    a.title, a.content = a.p_title, a.p_content
    a.category_id = a.p_category_id if a.p_category_id is not None else a.category_id
    a.labels = [x for x in a.p_labels or [] if x not in ("AI update", "New from link", "AI suggests removing", NEWER)]
    a.revision += 1
    a.status, a.reviewer, a.reviewed_at = "approved", actor, now()
    clear_proposal(a)
    log(db, a, kind, actor, revision=a.revision)


def reject(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    if a.status == "new":
        a.status = "rejected"
        log(db, a, "rejected", actor, note=note)
    elif a.status == "changed":
        clear_proposal(a)
        a.status = "approved"
        log(db, a, "change_rejected", actor, note=note)
    elif a.status == "removal":
        clear_proposal(a)
        a.status = "approved"
        log(db, a, "removal_rejected", actor, note=note)
    else:
        raise SnError("There is nothing waiting for review on this article.")
    a.reviewer, a.reviewed_at = actor, now()


def reopen(db: Session, a: SnArticle, actor: str) -> None:
    if a.status == "rejected" and a.p_content:
        a.status = "new"
    elif a.status == "removed" and a.content:
        a.status = "approved"
    else:
        raise SnError("This article cannot be reopened.")
    log(db, a, "reopened", actor)


# ── links: fetch, compare, ask the AI, turn its answer into proposals ─────────

def descendants(db: Session, cat_id: int) -> list[int]:
    rows = db.execute(select(SnCategory.id, SnCategory.parent_id).where(
        SnCategory.chatbot_id == db.scalar(select(SnCategory.chatbot_id).where(SnCategory.id == cat_id)))).all()
    kids: dict[int | None, list[int]] = {}
    for i, p in rows:
        kids.setdefault(p, []).append(i)
    out, todo = [], [cat_id]
    while todo:
        c = todo.pop()
        if c in out:
            continue
        out.append(c)
        todo += kids.get(c, [])
    return out


def _articles_for(db: Session, link: SnLink) -> list[SnArticle]:
    q = select(SnArticle).where(SnArticle.chatbot_id == link.chatbot_id, SnArticle.status.not_in(("rejected", "removed")))
    if link.article_id:
        q = q.where(SnArticle.id == link.article_id)
    else:
        ids = descendants(db, link.category_id)
        q = q.where((SnArticle.category_id.in_(ids)) | (SnArticle.p_category_id.in_(ids)))
    return list(db.scalars(q.order_by(SnArticle.id)))


def _fetch(url: str) -> dict:
    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(url)
    if r.status_code >= 400:
        raise SnError(f"The page answered HTTP {r.status_code}")
    if "html" not in r.headers.get("content-type", ""):
        raise SnError(f"Not a web page ({r.headers.get('content-type', 'unknown type').split(';')[0]})")
    d = extract(r.text, str(r.url))
    if not d["sections"]:
        raise SnError("No readable content on the page")
    return {"title": d["title"], "text": d["text"], "hash": d["hash"], "final": str(r.url)}


def apply_decisions(db: Session, link: SnLink, ev: SnLinkEvent, decisions: list[dict], sent: dict[int, str] | None = None) -> list[dict]:
    """Turn AI decisions into proposals. Returns the decisions annotated with what happened.
    `sent` = the article text the AI read; an article a person changed meanwhile is not overwritten."""
    db.flush()
    db.expire_all()                                           # the AI took a while: read what people did meanwhile
    out = []
    for d in decisions:
        res = dict(d)
        res.pop("content", None)
        if d["action"] == "new":
            a = SnArticle(chatbot_id=link.chatbot_id, category_id=link.category_id, status="new", p_title=d["title"], p_content=d["content"],
                          p_category_id=link.category_id, p_labels=["New from link"], p_kind="new", p_reason=d.get("reason"),
                          p_link_id=link.id, p_event_id=ev.id)
            db.add(a)
            db.flush()
            log(db, a, "proposed_new", "AI", link=link.url, reason=d.get("reason"))
            res.update(article_id=a.id, result="proposed")
        elif d["action"] in ("update", "remove"):
            a = db.get(SnArticle, d["article_id"])
            if a is None or a.status in ("rejected", "removed", "removal"):
                res["result"] = "skipped"
            elif sent is not None and current_text(a)[1] != sent.get(a.id):
                res["result"] = "skipped: a reviewer changed the article while the AI was reading it"
            elif d["action"] == "update":
                if a.status == "approved":
                    a.status, a.detected_at = "changed", now()
                    a.p_category_id, a.p_labels = a.category_id, sorted(set(a.labels or []) | {"AI update"})
                else:                                         # still waiting: revise the waiting proposal
                    a.p_labels = sorted(set(a.p_labels or []) | {"AI update"})   # an import keeps p_kind "import"
                a.p_title, a.p_content = d["title"] or a.p_title, d["content"]
                a.p_reason, a.p_link_id, a.p_event_id = d.get("reason"), link.id, ev.id
                if a.p_kind != "import":
                    a.p_kind = "update"
                log(db, a, "ai_update", "AI", link=link.url, reason=d.get("reason"))
                res["result"] = "proposed"
            else:
                if a.status == "approved":
                    clear_proposal(a)
                    a.status, a.detected_at, a.p_kind = "removal", now(), "remove"
                    a.p_reason, a.p_link_id, a.p_event_id = d.get("reason"), link.id, ev.id
                else:
                    a.p_labels = sorted(set(a.p_labels or []) | {"AI suggests removing"})
                    a.p_reason = d.get("reason")
                log(db, a, "ai_remove", "AI", link=link.url, reason=d.get("reason"))
                res["result"] = "proposed"
        else:
            res.setdefault("result", "no change")
        out.append(res)
    return out


def check_link(link_id: int, trigger: str = "manual", actor: str = "system", audit: bool = False) -> None:
    db = SessionLocal()
    try:
        link = db.get(SnLink, link_id)
        if link is None:
            return
        link.status = "checking"
        db.commit()
        cat = db.get(SnCategory, link.category_id)
        ev = SnLinkEvent(chatbot_id=link.chatbot_id, link_id=link.id, kind="audit" if audit else "changed", trigger=trigger, actor=actor)
        try:
            page = _fetch(link.url)
        except (httpx.HTTPError, SnError) as e:
            link.status, link.error, link.last_checked_at = "error", str(e) or type(e).__name__, now()
            ev.kind, ev.error, ev.summary = "error", link.error, f"Could not read the page: {link.error}"
            db.add(ev)
            _reschedule(link)
            db.commit()
            return
        link.title, link.error, link.last_checked_at = page["title"], None, now()
        first = link.content_hash is None
        if first and not audit:
            link.text, link.content_hash, link.status = page["text"], page["hash"], "ok"
            ev.kind, ev.summary = "baseline", "First read of the page. Future changes on it will be compared with this."
            db.add(ev)
            _reschedule(link)
            db.commit()
            return
        if not audit and page["hash"] == link.content_hash:
            link.status = "ok"
            _reschedule(link)
            db.commit()
            return
        diff, added, removed = line_diff(link.text or "", page["text"]) if not audit else ([], 0, 0)
        ev.diff, ev.added, ev.removed = diff, added, removed
        db.add(ev)
        arts = _articles_for(db, link)
        payload = [{"id": a.id, "title": current_text(a)[0], "content": current_text(a)[1]} for a in arts]
        db.commit()                                           # no transaction stays open while the AI reads
        try:
            decisions = sn_ai.reconcile(cat.path if cat else "", link.url, diff, page["text"], payload, audit=audit)
        except sn_ai.AIError as e:
            ev.error = str(e)
            ev.summary = ("The page changed, but the AI could not review it: " if not audit else "The AI check failed: ") + str(e)
            link.status, link.error = "error", str(e)        # the old text is kept, so the next check sees the change again
            _reschedule(link)
            db.commit()
            return
        link_id_, ev_id = link.id, ev.id
        ev.decisions = apply_decisions(db, link, ev, decisions, {p["id"]: p["content"] for p in payload})
        link, ev = db.get(SnLink, link_id_), db.get(SnLinkEvent, ev_id)
        n = {k: sum(1 for d in ev.decisions if d["action"] == k and d.get("result") == "proposed") for k in ("update", "new", "remove")}
        bits = [f"{n['update']} article update{'s' if n['update'] != 1 else ''}"] if n["update"] else []
        bits += [f"{n['new']} new article{'s' if n['new'] != 1 else ''}"] if n["new"] else []
        bits += [f"{n['remove']} removal{'s' if n['remove'] != 1 else ''}"] if n["remove"] else []
        ev.summary = (("Checked the articles against the page: " if audit else f"The page changed (+{added} −{removed} lines): ")
                      + (", ".join(bits) + " proposed for review" if bits else "no article needs to change"))
        if not audit:
            link.text, link.content_hash, link.last_changed_at = page["text"], page["hash"], now()
        link.status = "ok"
        record(db, link.chatbot_id, "link_check" if not audit else "link_audit", actor if trigger == "manual" else "Schedule",
               f"{link.url}: {ev.summary}", link_id=link.id, event_id=ev.id, **n)
        _reschedule(link)
        db.commit()
    except Exception as e:                                    # noqa: BLE001
        db.rollback()
        try:
            link = db.get(SnLink, link_id)
            if link:
                link.status, link.error = "error", f"{type(e).__name__}: {e}"[:500]
                db.add(SnLinkEvent(chatbot_id=link.chatbot_id, link_id=link.id, kind="error", trigger=trigger, actor=actor,
                                   error=traceback.format_exc()[-1500:], summary=f"Check failed: {type(e).__name__}"))
                db.commit()
        except Exception:                                     # noqa: BLE001
            db.rollback()
    finally:
        db.close()


def _reschedule(link: SnLink) -> None:
    link.next_run_at = now() + timedelta(hours=link.schedule_hours) if link.schedule_hours else None


# ── background worker (separate from the website crawl queue) ─────────────────

_queue: "queue.Queue[tuple]" = queue.Queue()
_pending: set[int] = set()
_lock = threading.Lock()


def enqueue(link_id: int, trigger: str = "manual", actor: str = "system", audit: bool = False) -> bool:
    with _lock:
        if link_id in _pending:
            return False
        _pending.add(link_id)
    _queue.put((link_id, trigger, actor, audit))
    return True


def busy_links() -> set[int]:
    with _lock:
        return set(_pending)


def _worker() -> None:
    while True:
        link_id, trigger, actor, audit = _queue.get()
        try:
            check_link(link_id, trigger, actor, audit)
        except Exception:                                     # noqa: BLE001
            pass                                              # check_link records its own failures; never let the worker die
        finally:
            with _lock:
                _pending.discard(link_id)


def _scheduler() -> None:
    while True:
        time.sleep(60)
        db = SessionLocal()
        try:
            for l in db.scalars(select(SnLink).where(SnLink.schedule_hours.is_not(None), SnLink.next_run_at <= now())):
                enqueue(l.id, "schedule", "schedule")
        except Exception:                                     # noqa: BLE001
            pass
        finally:
            db.close()


def start_background() -> None:
    db = SessionLocal()
    try:
        for l in db.scalars(select(SnLink).where(SnLink.status == "checking")):
            l.status = "error"
            l.error = "Interrupted by a server restart"
        db.commit()
        for l in db.scalars(select(SnLink).where(SnLink.status == "pending")):
            enqueue(l.id, "manual", "system")
    finally:
        db.close()
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_scheduler, daemon=True).start()


def add_link(db: Session, bot: Chatbot, category_id: int, url: str, actor: str, article_id: int | None = None,
             label: str = "", schedule_hours: int | None = 24) -> SnLink:
    c = canon(url or "")
    if not c or c.startswith(("http://localhost", "http://127.")):
        raise SnError("Enter the full web address, starting with https://")
    cat = db.get(SnCategory, category_id)
    if cat is None or cat.chatbot_id != bot.id:
        raise SnError("That category does not exist.")
    if article_id:
        a = db.get(SnArticle, article_id)
        if a is None or a.chatbot_id != bot.id:
            raise SnError("That article does not exist.")
    if db.scalar(select(SnLink.id).where(SnLink.category_id == category_id, SnLink.url == c)):
        raise SnError("That link is already on this category.")
    link = SnLink(chatbot_id=bot.id, category_id=category_id, article_id=article_id or None, url=c, label=label.strip()[:120],
                  schedule_hours=schedule_hours if schedule_hours and schedule_hours > 0 else None, created_by=actor)
    db.add(link)
    record(db, bot.id, "link_added", actor, f"Added the link {c} to “{cat.path}”", category=cat.path)
    db.commit()
    enqueue(link.id, "manual", actor)
    return link


# ── publishing ────────────────────────────────────────────────────────────────

def live_items(db: Session, bot: Chatbot) -> list[dict]:
    cats = {c.id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
    links = {l.id: l.url for l in db.scalars(select(SnLink).where(SnLink.chatbot_id == bot.id))}
    items = []
    for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.status.in_(LIVE), SnArticle.content.is_not(None))):
        c = cats.get(a.category_id)
        items.append({
            "entry_id": a.id, "title": a.title, "content": a.content, "category_id": a.category_id,
            "category": c.path if c else "Uncategorized", "category_position": c.position if c else 99999, "color": "slate",
            "secondary": [], "labels": [x for x in a.labels or [] if x not in ("AI update", "New from link")],
            "number": a.number, "source_url": kb_url(a.number), "source_title": a.number,
            "manual_edit": False, "revision": a.revision, "_order": (a.number or "~", a.id),
        })
    items.sort(key=lambda x: (x["category_position"], x["_order"]))
    for it in items:
        it.pop("_order")
    return items


def latest(db: Session, bot: Chatbot) -> SnVersion | None:
    return db.scalar(select(SnVersion).where(SnVersion.chatbot_id == bot.id).order_by(SnVersion.number.desc()).limit(1))


def draft(db: Session, bot: Chatbot) -> dict:
    last = latest(db, bot)
    items = live_items(db, bot)
    changes = publish.compare(last.items if last else [], items)
    waiting = db.scalar(select(func.count()).select_from(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.status.in_(QUEUE))) or 0
    return {"base_version": last.number if last else None, "next_version": (last.number if last else 0) + 1,
            "changes": changes, "counts": publish.counts(changes), "total": len(items), "waiting_review": waiting}


def publish_version(db: Session, bot: Chatbot, note: str, actor: str) -> SnVersion:
    d = draft(db, bot)
    if not d["changes"]:
        raise SnError("Nothing has changed since the last published version.")
    items = live_items(db, bot)
    v = SnVersion(chatbot_id=bot.id, number=d["next_version"], note=note.strip(), created_by=actor, items=items,
                  changes=d["changes"], stats={**d["counts"], "total": len(items)})
    db.add(v)
    st = v.stats
    record(db, bot.id, "published", actor, f"Published ServiceNow version {v.number}: {st.get('added', 0)} added, {st.get('modified', 0)} modified, "
           f"{st.get('removed', 0)} removed ({st.get('total', 0)} articles)", version=v.number)
    db.commit()
    return v


if __name__ == "__main__":                                     # python -m app.servicenow merge-versions
    import sys as _sys
    if _sys.argv[1:] != ["merge-versions"]:
        _sys.exit("usage: python -m app.servicenow merge-versions")
    with SessionLocal() as _db:
        for _bot in _db.scalars(select(Chatbot).order_by(Chatbot.id)).all():
            print(_bot.key, merge_versions(_db, _bot, "Duplicate clean-up"))
