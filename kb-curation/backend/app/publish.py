"""Publishing: the approved entries become an immutable, numbered KB version."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .diffing import line_diff
from .models import Category, Chatbot, Entry, KbVersion, Page

LIVE = ("approved", "changed", "removal")       # entries whose approved text is part of the KB right now


def live_items(db: Session, bot: Chatbot) -> list[dict]:
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.chatbot_id == bot.id))}
    rows = db.execute(select(Entry, Page).outerjoin(Page, Page.id == Entry.page_id)
                      .where(Entry.chatbot_id == bot.id, Entry.status.in_(LIVE), Entry.content.is_not(None))).all()
    items = []
    for e, p in rows:
        c = cats.get(e.category_id)
        items.append({
            "entry_id": e.id, "title": e.title, "content": e.content,
            "category_id": e.category_id, "category": c.name if c else "Uncategorized",
            "category_position": c.position if c else 9999, "color": c.color if c else "slate",
            "secondary": [cats[i].name for i in (e.secondary_ids or []) if i in cats],
            "labels": list(e.labels or []), "source_url": p.url if p else None, "source_title": p.title if p else None,
            "manual_edit": e.manual_edit, "revision": e.revision, "_order": (p.url if p else "", e.position),
        })
    items.sort(key=lambda x: (x["category_position"], x["_order"]))
    for it in items:
        it.pop("_order")
    return items


def _text(it: dict) -> str:
    return f"{it['title']}\n{it['content']}"


def compare(prev: list[dict], cur: list[dict]) -> list[dict]:
    """Entry-level changes between two snapshots, each with a line diff."""
    old, new = {i["entry_id"]: i for i in prev}, {i["entry_id"]: i for i in cur}
    out = []
    for eid, it in new.items():
        o = old.get(eid)
        if o is None:
            d, a, r = line_diff("", _text(it))
            out.append({"entry_id": eid, "change": "added", "title": it["title"], "category": it["category"], "source_url": it["source_url"],
                        "diff": d, "added": a, "removed": r, "meta": []})
            continue
        meta = []
        if o["category"] != it["category"]:
            meta.append(f"Category: {o['category']} → {it['category']}")
        if sorted(o.get("secondary", [])) != sorted(it.get("secondary", [])):
            meta.append(f"Also in: {', '.join(o.get('secondary', [])) or 'none'} → {', '.join(it.get('secondary', [])) or 'none'}")
        if sorted(o.get("labels", [])) != sorted(it.get("labels", [])):
            meta.append(f"Labels: {', '.join(o.get('labels', [])) or 'none'} → {', '.join(it.get('labels', [])) or 'none'}")
        if not meta and _text(o) == _text(it):
            continue
        d, a, r = line_diff(_text(o), _text(it), context=3)
        if d or meta:
            out.append({"entry_id": eid, "change": "modified", "title": it["title"], "category": it["category"], "source_url": it["source_url"],
                        "diff": d, "added": a, "removed": r, "meta": meta})
    for eid, o in old.items():
        if eid not in new:
            d, a, r = line_diff(_text(o), "")
            out.append({"entry_id": eid, "change": "removed", "title": o["title"], "category": o["category"], "source_url": o.get("source_url"),
                        "diff": d, "added": a, "removed": r, "meta": []})
    order = {"added": 0, "modified": 1, "removed": 2}
    out.sort(key=lambda c: (order[c["change"]], c["category"], c["title"]))
    return out


def latest(db: Session, bot: Chatbot) -> KbVersion | None:
    return db.scalar(select(KbVersion).where(KbVersion.chatbot_id == bot.id).order_by(KbVersion.number.desc()).limit(1))


def counts(changes: list[dict]) -> dict:
    c = {"added": 0, "modified": 0, "removed": 0}
    for ch in changes:
        c[ch["change"]] += 1
    return c


def draft(db: Session, bot: Chatbot) -> dict:
    last = latest(db, bot)
    items = live_items(db, bot)
    changes = compare(last.items if last else [], items)
    waiting = db.scalar(select(func.count()).select_from(Entry).where(Entry.chatbot_id == bot.id, Entry.status.in_(("new", "changed", "removal")))) or 0
    return {"base_version": last.number if last else None, "next_version": (last.number if last else 0) + 1,
            "changes": changes, "counts": counts(changes), "total": len(items), "waiting_review": waiting}


def publish(db: Session, bot: Chatbot, note: str, actor: str) -> KbVersion:
    d = draft(db, bot)
    if not d["changes"]:
        raise ValueError("Nothing has changed since the last published version.")
    items = live_items(db, bot)
    v = KbVersion(chatbot_id=bot.id, number=d["next_version"], note=note.strip(), created_by=actor, items=items,
                  changes=d["changes"], stats={**d["counts"], "total": len(items)})
    db.add(v)
    db.commit()
    return v
