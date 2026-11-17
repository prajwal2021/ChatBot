"""The SME's own knowledge base as a yardstick.

Ryan maintains a hand-written KB document ("If asked questions about X, answer with ..."). We read its topics, then
compare every entry the crawl produced with them. An entry that is close to a topic is "in Ryan's KB"; the rest is
information the chatbot was never meant to have, and is flagged so it can be rejected in one go.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from .config import CATEGORIZE_MODEL, OPENAI_API_KEY
from .db import SessionLocal
from .models import Chatbot, Entry, ScopeChunk, ScopeTopic

EMBED_MODEL = "text-embedding-3-small"
DEFAULT_THRESHOLD = 0.62
TOPIC_RE = re.compile(r"If asked\s+questions\s+about\s+(.+?),?\s+answer\s+with", re.I | re.S)
LIVE = ("new", "changed", "removal", "approved")
CLEAR_MARGIN = 0.08          # "clearly unrelated" = this far below the cutoff; closer than that is a judgement call for a person


class ScopeError(Exception):
    pass


def pdf_text(path: str) -> str:
    out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
    if out.returncode:
        raise ScopeError(f"Could not read the PDF: {out.stderr.strip()[:200]}")
    return out.stdout


def group_for(name: str, bot_key: str) -> str:
    n = name.lower()
    if bot_key == "k12":
        for g, words in (("Programs", ("program overview", "program requirements", "elementary", "gifted", "dual credit", "military")),
                         ("Tuition & billing", ("pricing", "refund", "w-9", "touchnet", "1098", "shipping", "textbook")),
                         ("Portals & support", ("portal", "softchalk", "counselor", "academic partnerships", "partnership", "transfer")),
                         ("Policies & testing", ("proctor", "grading", "credit by exam", "cbe", "disabilit", "grievance", "expectations", "fast-track"))):
            if any(w in n for w in words):
                return g
        return "General"
    for g, words in (("Master's degrees", ("master",)), ("Bachelor's degrees", ("bachelor", "b.a.", "b.s.")), ("Doctoral degrees", ("doctor",)),
                     ("Certificates", ("certificate", "microcredential", "career choice", "10-k")),
                     ("Enrollment & advising", ("enrollment", "advocate", "admitted", "admissions", "transition", "registration", "transcript", "support", "tuition", "cost", "experience"))):
        if any(w in n for w in words):
            return g
    return "General"


def parse(text: str, bot_key: str) -> list[dict]:
    text = text.replace("\f", "\n")
    ms = list(TOPIC_RE.finditer(text))
    topics, seen = [], {}
    for i, m in enumerate(ms):
        body = text[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(text)]
        body = re.sub(r"[ \t]+\n", "\n", body).strip()
        name = " ".join(m.group(1).split()).strip(" -–—")
        name = re.sub(r"^(the|about)\s+", "", name, flags=re.I)
        name = name[:1].upper() + name[1:]
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name} ({seen[name]})"
        if len(body.split()) < 8:
            continue
        topics.append({"name": name, "group": group_for(name, bot_key), "text": body, "words": len(body.split())})
    return topics


def chunks_of(name: str, text: str, size: int = 90) -> list[str]:
    out, cur, n = [], [], 0
    for para in re.split(r"\n\s*\n", text):
        w = len(para.split())
        if cur and n + w > size:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(para.strip())
        n += w
    if cur:
        out.append("\n".join(cur))
    return [f"{name}\n{c}"[:5000] for c in out if len(c.split()) >= 5] or [f"{name}\n{text}"[:5000]]


def embed(texts: list[str]) -> np.ndarray:
    if not OPENAI_API_KEY:
        raise ScopeError("Matching needs OPENAI_API_KEY in backend/.env.")
    batches = [texts[i:i + 64] for i in range(0, len(texts), 64)]

    def one(batch: list[str]) -> list[list[float]]:
        for attempt in range(4):
            try:
                r = httpx.post("https://api.openai.com/v1/embeddings", timeout=60, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                               json={"model": EMBED_MODEL, "input": batch})
                r.raise_for_status()
                return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
            except Exception:                                 # noqa: BLE001
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        return []

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [v for part in pool.map(one, batches) for v in part]
    a = np.array(rows, dtype=np.float32).reshape(len(texts), -1)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)


def import_topics(db: Session, bot: Chatbot, text: str) -> dict:
    topics = parse(text, bot.key)
    if not topics:
        raise ScopeError('No topics found. The document should contain lines like "If asked questions about …, answer with".')
    rows = [(t, chunks_of(t["name"], t["text"])) for t in topics]
    vecs = embed([c for _, cs in rows for c in cs])           # embed first: a failure leaves the old scope untouched
    db.execute(ScopeChunk.__table__.delete().where(ScopeChunk.chatbot_id == bot.id))
    db.execute(ScopeTopic.__table__.delete().where(ScopeTopic.chatbot_id == bot.id))
    k = 0
    for pos, (t, cs) in enumerate(rows):
        topic = ScopeTopic(chatbot_id=bot.id, name=t["name"], group=t["group"], position=pos, words=t["words"], text=t["text"])
        db.add(topic)
        db.flush()
        for c in cs:
            db.add(ScopeChunk(chatbot_id=bot.id, topic_id=topic.id, text=c, emb=vecs[k].round(5).tolist()))
            k += 1
    db.commit()
    return {"topics": len(rows), "chunks": k}


def entry_text(e: Entry) -> str:
    prop = e.status in ("new", "changed")
    title, content = (e.p_title, e.p_content) if prop else (e.title, e.content)
    content = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", content or "")
    return f"{title or ''}\n{content}"[:5000]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _shingles(words: list[str], n: int = 6) -> set[str]:
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def overlap(entry: Entry, kb: set[str]) -> float:
    """Share of the entry's 6-word phrases that appear word for word in the SME's KB (it was often copied from the site)."""
    prop = entry.status in ("new", "changed")
    content = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", (entry.p_content if prop else entry.content) or "")
    sh = _shingles(_words(content))
    return len(sh & kb) / len(sh) if len(sh) >= 5 else 0.0


BAND = (0.45, 0.72)          # scores in this range are borderline: an AI reads the entry and decides


def judge(topic_names: list[str], entries: list[Entry]) -> dict[int, bool]:
    """Ask a model whether borderline entries are the kind of fact the SME's topics cover. Returns {entry id: verdict}."""
    if not OPENAI_API_KEY or not entries:
        return {}
    system = ("You decide whether sections scraped from a website belong in a chatbot knowledge base. The knowledge base is written by a "
              "subject-matter expert and covers exactly these topics: " + "; ".join(topic_names) + ". A section belongs if it states facts, "
              "policies, steps, costs, dates, eligibility rules or contact routes that a parent, student or counselor could ask about under one "
              "of those topics. It does not belong if it is a staff or faculty profile or directory, meeting minutes, news or an event, a page "
              "footer or address block, navigation or marketing filler without facts, a bare list of links or forms, or about something none of "
              'the topics cover. Reply with JSON: {"results":[{"n":1,"in":true}, ...]} with one item per numbered section.')

    def one(batch: list[Entry]) -> dict[int, bool]:
        body = "\n\n".join(f"{i + 1}. {entry_text(e)[:420]}" for i, e in enumerate(batch))
        for attempt in range(3):
            try:
                r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=60, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                               json={"model": CATEGORIZE_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                                     "messages": [{"role": "system", "content": system}, {"role": "user", "content": body}]})
                r.raise_for_status()
                res = json.loads(r.json()["choices"][0]["message"]["content"])["results"]
                return {batch[int(x["n"]) - 1].id: bool(x["in"]) for x in res if 1 <= int(x["n"]) <= len(batch)}
            except Exception:                                 # noqa: BLE001
                time.sleep(2)
        return {}

    batches = [entries[i:i + 15] for i in range(0, len(entries), 15)]
    out: dict[int, bool] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for part in pool.map(one, batches):
            out.update(part)
    return out


def match(bot_id: int, only_new: bool = False) -> dict:
    """Compare entries with the SME's topics. Stores the closest topic and score on every entry."""
    db = SessionLocal()
    try:
        bot = db.get(Chatbot, bot_id)
        chunks = db.execute(select(ScopeChunk.topic_id, ScopeChunk.emb).where(ScopeChunk.chatbot_id == bot_id)).all()
        if not chunks:
            return {"checked": 0, "in_scope": 0, "outside": 0}
        thr = bot.scope_threshold or DEFAULT_THRESHOLD
        M = np.array([c[1] for c in chunks], dtype=np.float32)
        tids = np.array([c[0] for c in chunks])
        q = select(Entry).where(Entry.chatbot_id == bot_id, Entry.status.in_(LIVE))
        if only_new:
            q = q.where(Entry.in_scope.is_(None))
        es = list(db.scalars(q))
        if not es:
            return {"checked": 0, "in_scope": 0, "outside": 0}
        kb: set[str] = set()
        for (text,) in db.execute(select(ScopeTopic.text).where(ScopeTopic.chatbot_id == bot_id)):
            kb |= _shingles(_words(text))
        S = embed([entry_text(e) for e in es]) @ M.T
        best, score = S.argmax(1), S.max(1)
        for e, b, s in zip(es, best, score):
            ov = overlap(e, kb)
            s = max(float(s), 0.5 + 0.5 * ov) if ov >= 0.4 else float(s)      # word-for-word overlap is strong proof
            e.scope_topic_id, e.scope_score, e.in_scope, e.scope_verdict = int(tids[b]), round(s, 4), bool(s >= thr), None
        names = [t for (t,) in db.execute(select(ScopeTopic.name).where(ScopeTopic.chatbot_id == bot_id).order_by(ScopeTopic.position))]
        verdicts = judge(names, [e for e in es if BAND[0] <= e.scope_score < BAND[1]])
        for e in es:
            if e.id in verdicts:
                e.scope_verdict, e.in_scope = verdicts[e.id], verdicts[e.id]
        db.commit()
        n_in = sum(bool(e.in_scope) for e in es)
        return {"checked": len(es), "in_scope": n_in, "outside": len(es) - n_in}
    finally:
        db.close()


def apply_threshold(db: Session, bot: Chatbot) -> None:
    thr = bot.scope_threshold or DEFAULT_THRESHOLD
    db.execute(update(Entry).where(Entry.chatbot_id == bot.id, Entry.scope_score.is_not(None)).values(
        in_scope=case((Entry.scope_verdict.is_not(None), Entry.scope_verdict), else_=Entry.scope_score >= thr)))
