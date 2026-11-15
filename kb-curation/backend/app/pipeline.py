"""A crawl run: discover + fetch -> compare with the last crawl -> update pages, page events and entries.

Incremental by design: an unchanged page costs nothing, a changed page only touches the sections that changed,
and nothing reaches the published knowledge base without a reviewer.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import categorize, verify
from .crawler import Fetched, crawl
from .db import SessionLocal
from .diffing import line_diff, similar
from .extract import sha
from .models import Activity, Category, Chatbot, CrawlRun, Entry, EntryEvent, Page, PageEvent, Source, now

KEEP = "keep"
REMOVE_AFTER = 2          # consecutive "not found" crawls before a page counts as removed
_queue: "queue.Queue[int]" = queue.Queue()


def log(db: Session, e: Entry, action: str, actor: str = "system", **detail) -> None:
    db.add(EntryEvent(chatbot_id=e.chatbot_id, entry_id=e.id, action=action, actor=actor, detail=detail))


def record(db: Session, bot_id: int, area: str, action: str, actor: str, summary: str, **detail) -> None:
    db.add(Activity(chatbot_id=bot_id, area=area, action=action, actor=actor, summary=summary, detail=detail))


def clear_proposal(e: Entry) -> None:
    e.p_title = e.p_content = e.p_category_id = None
    e.p_secondary_ids, e.p_labels, e.p_edited = [], [], False


def propose_removal(db: Session, e: Entry, why: str) -> bool:
    """Returns True when a removal proposal was created."""
    if e.status in ("new", "rejected") and e.content is None:
        db.delete(e)                      # never approved: nothing to remove from the KB
        return False
    if e.status in ("removed", "removal") or e.content is None or e.rejected_hash == KEEP:
        return False                      # KEEP: a reviewer chose to keep this although the website dropped it
    clear_proposal(e)
    e.status, e.detected_at, e.source_hash = "removal", now(), None
    log(db, e, "removal_detected", reason=why)
    return True


GENERIC_PAGE = {"home", "index", "welcome", "untitled", ""}


def entry_title(page_title: str, heading: str) -> str:
    """Make a heading stand on its own: "Deadlines" on the page "How to Enroll" -> "How to Enroll: Deadlines"."""
    pt, h = (page_title or "").strip(), heading.strip()
    if pt.lower() in GENERIC_PAGE or pt.lower() in h.lower() or h.lower() in pt.lower() or len(pt) > 70:
        return h
    return f"{pt}: {h}"


def sync_entries(db: Session, bot: Chatbot, page: Page, sections: list[dict], cats: list[Category]) -> dict:
    """Bring a page's entries in line with its sections. Returns counts of proposals created."""
    stats = {"new": 0, "changed": 0, "removal": 0}
    sections = [{**s, "title": entry_title(page.title, s["title"])} for s in sections]
    sections = [{**s, "hash": sha(s["title"], s["content"])} for s in sections]
    existing = {e.key: e for e in db.scalars(select(Entry).where(Entry.page_id == page.id))}
    keys = {s["key"] for s in sections}
    orphans = [e for k, e in existing.items() if k not in keys and e.status not in ("removed",)]
    path = urlsplit(page.url).path

    for pos, s in enumerate(sections):
        e = existing.get(s["key"])
        if e is None:                     # a renamed heading keeps its entry (and its review history)
            for o in orphans:
                if similar(o.p_content or o.content or "", s["content"]) > 0.8:
                    orphans.remove(o)
                    o.key = s["key"]
                    e = o
                    break
        if e is None:
            primary, secondary = categorize.by_rules(cats, f"{s['title']} {page.title}", path, s["content"])
            e = Entry(chatbot_id=bot.id, page_id=page.id, key=s["key"], position=pos, status="new",
                      p_title=s["title"], p_content=s["content"], p_category_id=primary, p_secondary_ids=secondary,
                      p_labels=categorize.labels_for(s["title"], s["content"]), source_hash=s["hash"])
            twin = db.scalar(select(Entry.id).where(Entry.chatbot_id == bot.id, Entry.source_hash == s["hash"],
                                                    Entry.page_id != page.id, Entry.status.not_in(("rejected", "removed"))).limit(1))
            if page.found_via == "sitemap":
                e.p_labels = [*e.p_labels, "Not linked on site"]
            if twin:                      # the same text already exists on another page: flag it, do not hide it
                e.duplicate_of, e.p_labels = twin, [*e.p_labels, "Duplicate"]
            db.add(e)
            db.flush()
            log(db, e, "detected", page=page.url)
            stats["new"] += 1
            continue
        e.position = pos
        if e.source_hash == s["hash"]:
            continue                      # this section did not change on the website
        e.source_hash = s["hash"]
        if s["hash"] == e.rejected_hash:
            continue                      # the reviewer already said no to exactly this text
        if e.content is None or e.status == "removed":          # never approved, or removed and now back
            e.p_title, e.p_content, e.p_edited = s["title"], s["content"], False
            e.p_labels = categorize.labels_for(s["title"], s["content"])
            if e.p_category_id is None:
                e.p_category_id, e.p_secondary_ids = categorize.by_rules(cats, f"{s['title']} {page.title}", path, s["content"])
            if e.status != "new":
                e.status, e.detected_at = "new", now()
                stats["new"] += 1
                log(db, e, "detected", page=page.url)
        elif sha(e.title, e.content) == s["hash"]:               # website now matches what is approved
            clear_proposal(e)
            e.status, e.manual_edit = "approved", False
        else:
            was = e.status
            e.p_title, e.p_content, e.p_edited = s["title"], s["content"], False
            e.p_category_id, e.p_secondary_ids = e.category_id, list(e.secondary_ids or [])
            e.p_labels = sorted(set(e.labels or []) | set(categorize.labels_for(s["title"], s["content"])))
            e.status, e.detected_at = "changed", now()
            if was != "changed":
                stats["changed"] += 1
            log(db, e, "change_detected", page=page.url)

    for o in orphans:
        if propose_removal(db, o, "This section is no longer on the page"):
            stats["removal"] += 1
    return stats


def apply_result(db: Session, bot: Chatbot, src: Source, run: CrawlRun, f: Fetched, cats: list[Category], stats: dict) -> None:
    page = db.scalar(select(Page).where(Page.chatbot_id == bot.id, Page.url == f.url))
    is_new = page is None
    if is_new and not f.url.startswith(src.url):
        return                             # safety net: only hand-added pages may live outside the source
    if not is_new and page.status == "excluded":
        return                             # a person took this page out; only they can bring it back
    if f.kind == "file":
        stats["files"] += 1                # PDFs, images, documents: counted, never read or listed
        if page is not None and page.status == "skipped":
            db.delete(page)
        return
    if is_new and f.via != "link" and f.kind in ("missing", "error"):
        stats["sitemap_dead"] += 1
        return                             # stale sitemap lines are counted, not listed
    if is_new:
        page = Page(chatbot_id=bot.id, source_id=src.id, url=f.url, depth=f.depth, found_via="link" if f.via == "link" else "sitemap")
        db.add(page)
    elif f.via == "link":
        page.found_via = "link"
    elif f.via == "known" and page.status == "active" and page.found_via == "link" and f.kind == "page":
        page.found_via = "sitemap"         # the site no longer links to it
    page.source_id, page.http_status, page.last_run_id = src.id, f.http_status, run.id
    if f.http_status is not None or f.kind == "error":
        page.last_crawled_at = now()

    if f.kind == "skipped" and (f.reason or "").startswith("Excluded") and not is_new and page.status == "active":
        page.status, page.skip_reason = "skipped", f.reason          # a rule was added after the page was collected
        for e in db.scalars(select(Entry).where(Entry.page_id == page.id)):
            if propose_removal(db, e, "The page is now excluded by a rule on its source"):
                stats["entries_removal"] += 1
        stats["skipped"] += 1
        return
    if f.kind in ("file", "skipped"):
        if f.http_status is None and not is_new and page.status in ("active", "removed"):
            return                         # not fetched this time (e.g. over the page limit): leave it alone
        if page.status == "active" and page.content_hash and f.kind == "skipped":
            _page_removed(db, bot, page, run, stats, f.reason or "No longer a readable page")
        if page.status != "removed":
            page.status = "skipped"
        page.skip_reason = f.reason
        page.title = page.title or f.url.rstrip("/").rsplit("/", 1)[-1]
        stats["skipped"] += 1
        return
    if f.kind == "error":
        stats["errors"] += 1
        if is_new:
            page.status, page.skip_reason = "error", f.reason
        return                             # a timeout or 5xx never counts as a removal
    if f.kind == "missing":
        page.miss_count = (page.miss_count or 0) + 1
        if is_new:
            page.status, page.skip_reason = "error", "Linked from the site but the page does not exist"
            stats["errors"] += 1
        elif page.status == "active" and not page.content_hash:
            page.status, page.skip_reason = "error", "The page does not exist (not found)"
            stats["errors"] += 1
        elif page.status == "active" and page.miss_count >= REMOVE_AFTER:
            _page_removed(db, bot, page, run, stats, "The page was removed from the website")
        return

    data = f.data
    page.miss_count, page.title = 0, data["title"]
    if f.checks is not None:               # verified in this run (None = unchanged since the last verdict)
        page.checks, page.verified_hash = f.checks, data["hash"]
        page.verdict = "ok" if page.keep or not verify.failed_reason(f.checks) else "fail"
        stats["verified"] += 1
    if page.keep:
        page.verdict = "ok"                # a person overruled the automatic check
    if page.verdict == "fail":
        was_active = page.status == "active" and page.content_hash
        page.status, page.skip_reason = "skipped", "Did not pass verification: " + (verify.failed_reason(page.checks or []) or "see checks")
        page.content_hash, page.text = None, None
        stats["rejected"] += 1
        for e in db.scalars(select(Entry).where(Entry.page_id == page.id)) if not is_new else []:
            if propose_removal(db, e, page.skip_reason) and was_active:
                stats["entries_removal"] += 1
        return
    page.skip_reason = None
    old_text, old_hash, old_status = page.text, page.content_hash, page.status
    page.status = "active"
    if old_hash == data["hash"] and old_status == "active":
        stats["unchanged"] += 1
        return
    kind = "new" if not old_hash else "restored" if old_status == "removed" else "changed"
    diff, added, removed = line_diff("" if kind != "changed" else old_text or "", data["text"])
    page.text, page.content_hash = data["text"], data["hash"]
    page.last_changed_at, page.last_change_kind, page.changed_run_id = now(), kind, run.id
    page.change_count = (page.change_count or 0) + (1 if kind != "new" else 0)
    db.flush()
    db.add(PageEvent(chatbot_id=bot.id, page_id=page.id, run_id=run.id, kind=kind, added=added, removed=removed, diff=diff))
    stats["new" if kind == "new" else "changed" if kind == "changed" else "restored"] += 1
    es = sync_entries(db, bot, page, data["sections"], cats)
    for k, v in es.items():
        stats[f"entries_{k}"] += v


def _page_removed(db: Session, bot: Chatbot, page: Page, run: CrawlRun, stats: dict, why: str) -> None:
    diff, _, removed = line_diff(page.text or "", "")
    page.status, page.last_changed_at, page.last_change_kind, page.changed_run_id = "removed", now(), "removed", run.id
    page.skip_reason = why
    db.add(PageEvent(chatbot_id=bot.id, page_id=page.id, run_id=run.id, kind="removed", added=0, removed=removed, diff=diff))
    stats["removed"] += 1
    for e in db.scalars(select(Entry).where(Entry.page_id == page.id)):
        if propose_removal(db, e, why):
            stats["entries_removal"] += 1


def recategorize(bot_id: int, since=None) -> dict:
    """Ask the model to re-file entries that are still waiting as new and that no reviewer has touched."""
    from concurrent.futures import ThreadPoolExecutor

    db = SessionLocal()
    try:
        cats = list(db.scalars(select(Category).where(Category.chatbot_id == bot_id).order_by(Category.position)))
        rows = db.execute(select(Entry, Page).join(Page, Page.id == Entry.page_id)
                          .where(Entry.chatbot_id == bot_id, Entry.status == "new", Entry.reviewer.is_(None),
                                 *([Entry.created_at >= since] if since else []))
                          .order_by(Page.id, Entry.position)).all()
        touched = set(db.scalars(select(EntryEvent.entry_id).where(EntryEvent.chatbot_id == bot_id, EntryEvent.action == "edited")))
        pages: dict[int, tuple[Page, list[Entry]]] = {}
        for e, p in rows:
            if e.id not in touched:
                pages.setdefault(p.id, (p, []))[1].append(e)

        def work(item):
            p, es = item
            secs = [{"key": str(e.id), "title": e.p_title or "", "content": e.p_content or ""} for e in es]
            return es, categorize.by_llm(cats, p.title, p.url, secs)

        stats = {"entries": 0, "moved": 0, "failed_pages": 0}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for es, res in pool.map(work, pages.values()):
                if res is None:
                    stats["failed_pages"] += 1
                    continue
                for e in es:
                    got = res.get(str(e.id))
                    if not got or not got[0]:
                        continue
                    stats["entries"] += 1
                    if got[0] != e.p_category_id:
                        stats["moved"] += 1
                    e.p_category_id, e.p_secondary_ids = got
        db.commit()
        return stats
    finally:
        db.close()


def verify_results(db: Session, bot: Chatbot, results: dict[str, Fetched], progress) -> None:
    """Fill f.checks for every fetched page whose content is new or changed since its last verdict."""
    known = {p.url: p for p in db.scalars(select(Page).where(Page.chatbot_id == bot.id))}
    first_with: dict[str, str] = {}
    for f in sorted((f for f in results.values() if f.kind == "page"), key=lambda x: (x.via != "link", x.depth, len(x.url), x.url)):
        first_with.setdefault(f.data["hash"], f.url)          # the page people actually reach is the original
    todo: list[tuple[str, dict]] = []
    for f in results.values():
        if f.kind != "page":
            continue
        p = known.get(f.url)
        if p is not None and (p.status == "excluded" or (p.verified_hash == f.data["hash"] and p.verdict)):
            continue                                          # unchanged since its last verdict
        twin = first_with[f.data["hash"]]
        f.checks = verify.basic_checks(f.data, twin if twin != f.url else None)
        if not verify.failed_reason(f.checks) and not (p is not None and p.keep):
            todo.append((f.url, f.data))
    for url, check in verify.ai_checks(bot.description or bot.name, todo, progress).items():
        results[url].checks.append(check)


def execute(run_id: int) -> None:
    db = SessionLocal()
    try:
        run = db.get(CrawlRun, run_id)
        bot = db.get(Chatbot, run.chatbot_id)
        run.status, run.stage, run.started_at = "running", "discovering", now()
        db.commit()
        cats = list(db.scalars(select(Category).where(Category.chatbot_id == bot.id).order_by(Category.position)))
        stats = {k: 0 for k in ("discovered", "pages", "new", "changed", "removed", "restored", "unchanged", "skipped",
                                "errors", "entries_new", "entries_changed", "entries_removal", "sitemap_dead", "files", "verified", "rejected")}
        q = select(Source).where(Source.chatbot_id == bot.id)
        if run.source_id:
            q = q.where(Source.id == run.source_id)
        for src in db.scalars(q.order_by(Source.id)):
            known = list(db.scalars(select(Page.url).where(Page.chatbot_id == bot.id, Page.source_id == src.id, Page.status == "active")))
            last = [0.0]

            def progress(done: int, found: int, url: str, _src=src):
                if time.time() - last[0] > 0.7:
                    last[0] = time.time()
                    run.progress = {"fetched": done, "found": found, "current": url, "source": _src.url}
                    db.commit()

            skip = set(db.scalars(select(Page.url).where(Page.chatbot_id == bot.id, Page.status == "excluded")))
            results = crawl(src.url, src.max_pages, known, progress, exclude=src.exclude or [], skip=skip)
            run.stage, run.progress = "verifying", {"fetched": 0, "found": sum(f.kind == "page" for f in results.values()), "source": src.url}
            db.commit()

            def vprogress(done: int, total: int, url: str):
                if time.time() - last[0] > 0.7:
                    last[0] = time.time()
                    run.progress = {"fetched": done, "found": total, "current": url}
                    db.commit()

            verify_results(db, bot, results, vprogress)
            run.stage = "comparing"
            run.progress = {"fetched": len(results), "found": len(results), "source": src.url, "applied": 0}
            db.commit()
            for i, f in enumerate(sorted(results.values(), key=lambda x: (x.depth, x.url))):
                apply_result(db, bot, src, run, f, cats, stats)
                if i % 25 == 0:
                    run.progress = {**run.progress, "applied": i}
                    db.commit()
            stats["discovered"] += len(results)
            src.last_run_at = now()
            if src.schedule_hours:
                src.next_run_at = now() + timedelta(hours=src.schedule_hours)
            db.commit()
            run.stage = "discovering"
        if stats["entries_new"] and categorize.OPENAI_API_KEY:
            run.stage, run.progress = "categorising", {}
            db.commit()
            recategorize(bot.id, since=run.started_at)
        stats["pages"] = len(list(db.scalars(select(Page.id).where(Page.chatbot_id == bot.id, Page.status == "active"))))
        run.stats, run.status, run.stage, run.finished_at, run.progress = stats, "done", "done", now(), {}
        bits = [f"{stats[k]} {label}" for k, label in (("new", "new pages"), ("changed", "updated"), ("removed", "removed"), ("rejected", "failed verification")) if stats[k]]
        record(db, bot.id, "pages", "crawl", run.created_by if run.trigger == "manual" else "Schedule",
               "Checked the websites: " + (", ".join(bits) if bits else "no changes") + f" ({stats['pages']} pages tracked)", run_id=run.id, **stats)
        db.commit()
    except Exception as e:                                    # noqa: BLE001
        db.rollback()
        run = db.get(CrawlRun, run_id)
        if run:
            run.status, run.stage, run.error, run.finished_at = "failed", "failed", f"{e}\n{traceback.format_exc()[-1500:]}", now()
            db.commit()
    finally:
        db.close()


def start_run(db: Session, bot: Chatbot, source_id: int | None, trigger: str, actor: str) -> CrawlRun:
    active = db.scalar(select(CrawlRun).where(CrawlRun.chatbot_id == bot.id, CrawlRun.status.in_(("queued", "running"))))
    if active:
        return active
    run = CrawlRun(chatbot_id=bot.id, source_id=source_id, trigger=trigger, created_by=actor)
    db.add(run)
    db.commit()
    _queue.put(run.id)
    return run


def _worker() -> None:
    while True:
        execute(_queue.get())


def _scheduler() -> None:
    while True:
        time.sleep(60)
        db = SessionLocal()
        try:
            due = db.scalars(select(Source).where(Source.schedule_hours.is_not(None), Source.next_run_at <= now())).all()
            for bot_id in {s.chatbot_id for s in due}:
                start_run(db, db.get(Chatbot, bot_id), None, "schedule", "schedule")
            for s in due:
                s.next_run_at = now() + timedelta(hours=s.schedule_hours)
            db.commit()
        except Exception:                                     # noqa: BLE001
            db.rollback()
        finally:
            db.close()


def start_background() -> None:
    db = SessionLocal()
    try:                                                      # runs interrupted by a restart
        for r in db.scalars(select(CrawlRun).where(CrawlRun.status.in_(("queued", "running")))):
            r.status, r.stage, r.error, r.finished_at = "failed", "failed", "Interrupted by a server restart", now()
        db.commit()
    finally:
        db.close()
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_scheduler, daemon=True).start()
