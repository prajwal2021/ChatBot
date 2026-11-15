"""Categories and labels for an entry.

An entry gets one primary category (where it sits in the document) and up to two secondary categories
(it also shows under those in the UI and is tagged with them for the chatbot), because one piece of content
often answers questions from two angles, e.g. "Credit by Exam fees" is both Testing and Tuition & Fees.
Rules are keyword based; set OPENAI_API_KEY to let a model decide instead (rules remain the fallback).
"""
from __future__ import annotations

import json
import re

import httpx

from .config import CATEGORIZE_MODEL, OPENAI_API_KEY

COLORS = ["blue", "emerald", "amber", "violet", "rose", "cyan", "orange", "teal", "indigo", "pink", "lime", "slate"]

K12 = [
    ("Enrollment & Admissions", "How to enroll, apply, register and get started", ["enroll", "enrollment", "admission", "apply", "application", "register", "registration", "get started", "transcript", "withdraw"]),
    ("Tuition & Fees", "Costs, payment, refunds and tuition-free eligibility", ["tuition", "fee", "fees", "cost", "payment", "refund", "price", "pricing", "financial", "tuition-free", "freetuition", "scholarship", "$"]),
    ("Programs & Diplomas", "Full-time and part-time programs, diplomas and grade levels", ["program", "diploma", "full-time", "fulltime", "elementary", "middle school", "high school", "kindergarten", "homeschool", "curriculum"]),
    ("Courses & Catalog", "Individual, supplemental, AP and summer courses", ["course", "courses", "catalog", "supplemental", "advanced placement", "summer", "elective", "syllabus", "credit recovery"]),
    ("Dual Credit", "College credit while in high school", ["dual credit", "dual-credit", "college credit", "dualcredit"]),
    ("Testing & Credit by Exam", "CBEs, STAAR, proctoring and exam scheduling", ["credit by exam", "cbe", "cbes", "exam", "staar", "proctor", "testing", "test", "end-of-course", "eoc", "assessment"]),
    ("Graduation & Academics", "Graduation requirements, grades, transcripts and class rank", ["graduation", "graduate", "grade", "gpa", "class rank", "requirements", "credits", "transcript", "commencement", "honor"]),
    ("Student & Family Support", "Advising, counseling, learning coaches and student resources", ["advisor", "advising", "counselor", "counseling", "learning coach", "parent", "family", "accommodation", "504", "special education", "tutoring", "student organizations", "honor society", "clubs"]),
    ("Technology & Access", "Logins, learning platform, system requirements and tech help", ["login", "log in", "password", "canvas", "technology", "technical", "browser", "computer", "system requirements", "portal", "help desk"]),
    ("Schools & Partnerships", "District, school and international partners", ["district", "partner", "partnership", "schools", "international", "brazil", "educator", "administrator"]),
    ("Policies & Accountability", "Policies, accreditation, reports and governance", ["policy", "policies", "handbook", "conduct", "attendance", "truancy", "grievance", "accreditation", "accredited", "accountability", "advisory board", "board meeting", "compliance", "privacy", "nondiscrimination"]),
    ("Contact & About", "Who we are, contact details, staff, hours and news", ["contact", "phone", "email", "office hours", "staff", "directory", "about", "mission", "history", "news", "location", "address"]),
]

ONLINE = [
    ("Programs & Degrees", "Online bachelor's, master's, doctoral and certificate programs", ["program", "degree", "bachelor", "master", "doctor", "doctoral", "certificate", "major", "minor", "curriculum", "concentration"]),
    ("Admissions & Applying", "How to apply, requirements, deadlines and transfer credit", ["admission", "admissions", "apply", "application", "transfer", "requirements", "deadline", "transcript", "readmission", "eligib"]),
    ("Tuition & Financial Aid", "Costs, fees, scholarships, aid and payment", ["tuition", "fee", "fees", "cost", "financial aid", "scholarship", "fafsa", "payment", "affordable", "waiver", "$"]),
    ("Online+ Experience", "8-week courses, credit for experience and Online+ features", ["online+", "online plus", "8-week", "8‑week", "accelerated", "prior learning", "work-life", "career certificate"]),
    ("Courses & Registration", "Registering for classes, course formats, calendars and exams", ["course", "courses", "register", "registration", "schedule", "calendar", "semester", "proctor", "exam", "asynchronous", "synchronous", "hybrid"]),
    ("Student Support & Services", "Advising, tutoring, library, career and accessibility services", ["advisor", "advising", "tutoring", "library", "career", "support", "services", "success", "disability", "accessib", "veteran", "military", "orientation"]),
    ("Technology & Access", "Logins, learning platforms and technical help", ["login", "canvas", "blackboard", "eraider", "password", "technology", "technical", "it help", "software", "system requirements"]),
    ("Regional Sites & Locations", "Regional teaching sites and physical locations", ["regional", "site", "campus", "location", "waco", "el paso", "fredericksburg", "highland lakes", "junction", "collin", "costa rica"]),
    ("State Authorization & Policies", "State authorization, licensure, complaints and policies", ["state authorization", "licensure", "sara", "complaint", "policy", "policies", "accreditation", "compliance", "out-of-state", "disclosure"]),
    ("Faculty & Staff Resources", "Resources for people teaching or building online courses", ["faculty", "instructor", "instructional design", "teaching", "course development", "staff", "quality matters"]),
    ("Contact & About", "Who we are, contact details, rankings, events and news", ["contact", "phone", "email", "about", "ranking", "news", "event", "webinar", "request information", "mission"]),
]

GENERIC = [
    ("Admissions & Enrollment", "Applying, enrolling and registering", ["admission", "apply", "enroll", "register", "application"]),
    ("Costs & Aid", "Tuition, fees and financial help", ["tuition", "fee", "cost", "aid", "scholarship", "payment", "$"]),
    ("Programs & Courses", "What is offered", ["program", "course", "degree", "curriculum"]),
    ("Support & Services", "Help and resources", ["support", "advising", "services", "resources", "help"]),
    ("Policies", "Rules, policies and compliance", ["policy", "policies", "compliance", "accreditation"]),
    ("Contact & About", "Contact details and general information", ["contact", "phone", "email", "about", "news"]),
]


def seed_for(bot_key: str) -> list[tuple[str, str, list[str]]]:
    return K12 if "k12" in bot_key or "k-12" in bot_key else ONLINE if "online" in bot_key else GENERIC


LABEL_RULES = [
    ("Costs", re.compile(r"\$\s?\d")),
    ("Deadlines & dates", re.compile(r"\bdeadline|\bdue (by|date)|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}\b", re.I)),
    ("Contact info", re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+")),
    ("How-to steps", re.compile(r"(^|\n)\s*1\. .+\n\s*2\. ", re.S)),
    ("Eligibility", re.compile(r"\beligib|\bqualif|\bmust (be|have)\b|\brequirement", re.I)),
    ("Forms", re.compile(r"\bforms?\b", re.I)),
    ("FAQ", re.compile(r"\bfaq|frequently asked|\?\s*$", re.I | re.M)),
    ("Table", re.compile(r".+ \| .+\n.+ \| .+")),
]


def labels_for(title: str, content: str) -> list[str]:
    text = f"{title}\n{content}"
    out = [name for name, rx in LABEL_RULES if rx.search(text)][:5]
    if len(content) > 6000:
        out.append("Long entry")
    return out


def _score(cat, title: str, path: str, content: str) -> float:
    head, body = f"{title} {path}".lower().replace("-", " "), content.lower()
    s = 0.0
    for kw in cat.keywords or []:
        kw = kw.lower()
        if kw in head:
            s += 4
        s += min(body.count(kw), 3)
    return s


def by_rules(cats, title: str, path: str, content: str) -> tuple[int | None, list[int]]:
    scored = sorted(((_score(c, title, path, content), -c.position, c.id) for c in cats), reverse=True)
    scored = [(s, cid) for s, _, cid in scored if s >= 2]
    if not scored:
        return None, []
    top, primary = scored[0]
    return primary, [cid for s, cid in scored[1:3] if s >= max(5, top * 0.7)]


def _match(names: dict, value) -> int | None:
    """Category id for a name the model returned; tolerates a shortened or slightly reworded name."""
    v = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    if not v:
        return None
    clean = {re.sub(r"[^a-z0-9]+", " ", k).strip(): i for k, i in names.items()}
    if v in clean:
        return clean[v]
    near = [i for k, i in clean.items() if k.startswith(v) or v.startswith(k)]
    return near[0] if len(near) == 1 else None


def _llm_batch(cats, names: dict, page_title: str, url: str, batch: list[dict]) -> dict:
    system = ("You file sections of a university web page into knowledge-base categories for a chatbot.\n"
              "For EVERY numbered section return one result with its number. Choose exactly one primary category: the one "
              "a person asking about this section's main subject would look under. Add a secondary category (at most two) "
              "ONLY when the section also contains concrete facts that answer questions in that other area, e.g. a "
              "Credit by Exam section that states its fee is primary Testing, secondary Tuition & Fees. Most sections "
              "have no secondary. Judge by the section's own content first, the page second. Use category names exactly "
              "as listed, or null when none fits.\n"
              'Respond with JSON: {"sections": [{"n": 1, "primary": "", "secondary": []}]}\n\nCATEGORIES\n'
              + "\n".join(f"- {c.name}: {c.description}" for c in cats))
    user = f"PAGE: {page_title} ({url})\n\n" + "\n\n".join(
        f"SECTION {i}: {s['title']}\n{s['content'][:700]}" for i, s in enumerate(batch, 1))
    r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=35,
                   headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                   json={"model": CATEGORIZE_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    r.raise_for_status()
    out = {}
    for row in json.loads(r.json()["choices"][0]["message"]["content"]).get("sections", []):
        n = row.get("n")
        if not isinstance(n, int) or not 1 <= n <= len(batch):
            continue
        p = _match(names, row.get("primary"))
        sec = [m for m in (_match(names, x) for x in (row.get("secondary") or [])) if m]
        out[batch[n - 1]["key"]] = (p, [x for x in dict.fromkeys(sec) if x != p][:2])
    return out


def by_llm(cats, page_title: str, url: str, sections: list[dict]) -> dict[str, tuple[int | None, list[int]]] | None:
    """Returns {section key: (primary, secondary)} for the sections the model answered; None when it is unavailable.
    Sections it skipped are simply absent, so the caller falls back to the keyword rules for those."""
    if not OPENAI_API_KEY or not sections:
        return None
    names = {c.name.lower(): c.id for c in cats}
    out: dict = {}
    ok = False
    for i in range(0, len(sections), 20):
        try:
            out.update(_llm_batch(cats, names, page_title, url, sections[i:i + 20]))
            ok = True
        except Exception:                                     # noqa: BLE001
            continue
    return out if ok else None
