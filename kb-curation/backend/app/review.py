"""Reviewer actions on entries: edit, approve, reject, comment. Every action is written to the audit trail."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .extract import norm
from .models import Category, Entry, now
from .pipeline import KEEP, clear_proposal, log


SYSTEM_LABELS = ("Duplicate", "Not linked on site", "Long entry")


class ReviewError(Exception):
    pass


def has_proposal(e: Entry) -> bool:
    return e.status in ("new", "changed") or (e.status == "rejected" and e.content is None)


def _check_cats(db: Session, e: Entry, ids: list[int]) -> None:
    ok = set(db.scalars(select(Category.id).where(Category.chatbot_id == e.chatbot_id)))
    if any(i not in ok for i in ids):
        raise ReviewError("That category does not exist for this chatbot.")


def edit(db: Session, e: Entry, actor: str, *, title=None, content=None, category_id=None, secondary_ids=None, labels=None) -> None:
    if e.status in ("removal", "removed"):
        raise ReviewError("This entry is being removed and cannot be edited. Reject the removal first to keep it.")
    _check_cats(db, e, ([category_id] if category_id else []) + list(secondary_ids or []))
    if title is not None and not norm(title):
        raise ReviewError("The title cannot be empty.")
    if content is not None and not norm(content):
        raise ReviewError("The content cannot be empty.")
    prop = has_proposal(e)
    cur_title, cur_content = (e.p_title, e.p_content) if prop else (e.title, e.content)
    text_changed = (title is not None and title.strip() != cur_title) or (content is not None and content.strip() != cur_content)
    before = {"title": cur_title, "content": cur_content}
    pre = "p_" if prop else ""
    if title is not None:
        setattr(e, pre + "title", title.strip())
    if content is not None:
        setattr(e, pre + "content", "\n".join(x.rstrip() for x in content.strip().splitlines()))
    if category_id is not None:
        setattr(e, pre + "category_id", category_id or None)
    if secondary_ids is not None:
        primary = getattr(e, pre + "category_id")
        setattr(e, pre + "secondary_ids", [i for i in dict.fromkeys(secondary_ids) if i != primary][:3])
    elif category_id is not None:
        setattr(e, pre + "secondary_ids", [i for i in getattr(e, pre + "secondary_ids") or [] if i != category_id])
    if labels is not None:
        setattr(e, pre + "labels", [x for x in dict.fromkeys(norm(l)[:40] for l in labels) if x][:8])
    if prop:
        e.p_edited = e.p_edited or text_changed
    else:
        e.revision += 1
        e.manual_edit = e.manual_edit or text_changed
        e.reviewer, e.reviewed_at = actor, now()
    log(db, e, "edited", actor, text_changed=text_changed, **(before if text_changed else {}))


def approve(db: Session, e: Entry, actor: str) -> None:
    if e.status == "removal":
        e.status, e.reviewer, e.reviewed_at = "removed", actor, now()
        log(db, e, "removal_approved", actor)
        return
    if not has_proposal(e):
        raise ReviewError("There is nothing waiting for approval on this entry.")
    if not e.p_category_id:
        raise ReviewError("Choose a category before approving.")
    kind = "change_approved" if e.content is not None else "approved"
    e.title, e.content, e.category_id = e.p_title, e.p_content, e.p_category_id
    e.secondary_ids = list(e.p_secondary_ids or [])
    e.labels = [x for x in e.p_labels or [] if x not in SYSTEM_LABELS]      # review flags are not knowledge
    e.manual_edit, e.revision = bool(e.p_edited), e.revision + 1
    e.status, e.reviewer, e.reviewed_at, e.rejected_hash = "approved", actor, now(), None
    clear_proposal(e)
    log(db, e, kind, actor, revision=e.revision)


def reject(db: Session, e: Entry, actor: str, note: str = "") -> None:
    if e.status == "new":
        e.status, e.rejected_hash = "rejected", e.source_hash
        log(db, e, "rejected", actor, note=note)
    elif e.status == "changed":
        clear_proposal(e)
        e.status, e.rejected_hash, e.manual_edit = "approved", e.source_hash, True
        log(db, e, "change_rejected", actor, note=note)
    elif e.status == "removal":
        e.status, e.rejected_hash, e.manual_edit = "approved", KEEP, True
        log(db, e, "removal_rejected", actor, note=note)
    else:
        raise ReviewError("There is nothing waiting for review on this entry.")
    e.reviewer, e.reviewed_at = actor, now()


def reopen(db: Session, e: Entry, actor: str) -> None:
    """Bring a rejected or removed entry back into the review queue."""
    if e.status == "rejected" and e.p_content:
        e.status, e.rejected_hash = "new", None
    elif e.status == "removed" and e.content:
        e.status, e.rejected_hash = "approved", KEEP
        e.manual_edit = True
    else:
        raise ReviewError("This entry cannot be reopened.")
    log(db, e, "reopened", actor)
