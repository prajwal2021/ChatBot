"""ServiceNow article HTML -> the plain line format the rest of the app uses.

One item per line: "## " / "### " headings, sentences, "- " bullets, "1. " steps, table rows "a | b",
links as [text](url) and images on their own line as ![alt](src). Images stored in ServiceNow are written as
sn-asset:<sys_id> so they resolve to the copy kept by this app, wherever the API is served.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .extract import norm

BR = "\x00"
DROP = ["script", "style", "noscript", "form", "button", "select", "template", "svg"]
BLOCKS = {"p", "div", "section", "article", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
          "dl", "dt", "dd", "figure", "figcaption", "details", "summary", "pre", "hr", "li", "tr", "center"}
LAYOUT_BLOCKS = ["p", "ul", "ol", "div", "h1", "h2", "h3", "h4", "table"]
BULLET = re.compile(r"^[·•▪◦§o]\s+(?=\S)")
LEGACY_KEYS = {"title", "location", "last updated", "content", "article keywords"}
ATTACH = re.compile(r"sys_attachment\.do\?sys_id=([0-9a-fA-F]{32})|/([0-9a-fA-F]{32})\.iix")

# which template fields hold the article body, in reading order (heading shown above each part, or None)
TEMPLATE_PARTS = {
    "kb_template_faq": [("kb_question", None), ("kb_answer", None)],
    "kb_template_how_to": [("kb_introduction", None), ("kb_instructions", None)],
    "kb_template_what_is": [("kb_introduction", None), ("kb_explanation", None)],
    "kb_template_incident_kcs_article_html": [("kb_issue", "Issue"), ("kb_resolution", "Resolution")],
}


def asset_id(src: str) -> str | None:
    m = ATTACH.search(src.replace("&#61;", "="))
    if m:
        return (m.group(1) or m.group(2)).lower()
    q = parse_qs(urlsplit(src).query)
    v = (q.get("sys_id") or [""])[0]
    return v.lower() if re.fullmatch(r"[0-9a-fA-F]{32}", v) else None


def image_ids(html: str) -> set[str]:
    return {(a or b).lower() for a, b in ATTACH.findall((html or "").replace("&#61;", "="))}


class _Conv:
    def __init__(self, base: str):
        self.base = base
        self.lines: list[str] = []
        self.buf: list[str] = []

    def flush(self):
        if self.buf:
            for x in "".join(self.buf).split(BR):
                t = norm(x).replace(")[", ") · [")
                if t:
                    self.lines.append(t)
            self.buf = []

    def emit(self, line: str):
        self.flush()
        if line:
            self.lines.append(line)

    def img(self, n: Tag) -> str:
        src = (n.get("src") or "").strip()
        alt = norm(n.get("alt") or n.get("title") or "").replace("]", ")").replace("[", "(") or "Image"
        aid = asset_id(src) if "sys_attachment" in src or ".iix" in src else None
        if aid:
            return f"{BR}![{alt}](sn-asset:{aid}){BR}"
        if src.startswith(("http://", "https://")):
            return f"{BR}![{alt}]({src}){BR}"
        return ""

    def inline(self, el) -> str:
        out: list[str] = []
        for n in el.children:
            if isinstance(n, Comment):
                continue
            if isinstance(n, NavigableString):
                out.append(re.sub(r"\s+", " ", str(n)))
            elif not isinstance(n, Tag):
                continue
            elif n.name == "br":
                out.append(BR)
            elif n.name == "img":
                out.append(self.img(n))
            elif n.name in ("ul", "ol", "table"):
                continue
            elif n.name == "iframe":
                src = n.get("src") or ""
                if src.startswith(("http://", "https://", "//")):
                    out.append(f"{BR}[Video]({urljoin('https:', src)}){BR}")
            elif n.name == "a":
                inner = self.inline(n)
                text = norm(inner.replace(BR, " "))
                href = (n.get("href") or "").strip()
                imgs = re.findall(r"!\[[^\]]*\]\([^)]*\)", inner)
                if imgs and not re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text).strip():
                    out.append(inner)                         # a linked screenshot: keep the image
                    continue
                if not text:
                    continue
                if href.lower().startswith("mailto:"):
                    addr = href[7:].split("?")[0]
                    out.append(text if addr.lower() in text.lower() else f"{text} ({addr})")
                elif not href or href.startswith("#") or href.lower().startswith(("javascript", "tel:")):
                    out.append(text)
                else:
                    out.append(f"[{text}]({urljoin(self.base, href)})")
            else:
                out.append(self.inline(n))
        return "".join(out)

    def lst(self, el: Tag, depth: int = 0):
        i = 0
        for li in el.find_all("li", recursive=False):
            i += 1
            raw = self.inline(li)
            parts = [norm(x) for x in raw.split(BR)]
            text = " ".join(p for p in parts if p and not p.startswith("![")).replace(")[", ") · [")
            if text:
                self.emit("  " * depth + (f"{i}. " if el.name == "ol" else "- ") + text)
            for p in parts:
                if p.startswith("!["):
                    self.emit(p)
            for sub in li.find_all(["ul", "ol"], recursive=False):
                self.lst(sub, depth + 1)
            for t in li.find_all("table", recursive=False):
                self.table(t)

    def table(self, n: Tag):
        self.flush()
        rows = [tr for tr in n.find_all("tr") if tr.find_parent("table") is n]
        keyed = {}
        for tr in rows:
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) == 2:
                keyed[norm(cells[0].get_text(" ")).rstrip(":").lower()] = cells[1]
        if "content" in keyed and len(set(keyed) & LEGACY_KEYS) >= 2:
            self.walk(keyed["content"])                       # old K-12 layout: a Title/Location/Content form; keep the content
            self.flush()
            return
        ncols = max((len(tr.find_all(["th", "td"], recursive=False)) for tr in rows), default=0)
        blocky = any(len([b for b in c.find_all(LAYOUT_BLOCKS) if b.find_parent(["td", "th"]) is c]) >= 2
                     for tr in rows for c in tr.find_all(["th", "td"], recursive=False))
        if ncols <= 2 and blocky:                             # a layout table holding paragraphs or lists: read it as text
            for tr in rows:
                for c in tr.find_all(["th", "td"], recursive=False):
                    self.walk(c)
                    self.flush()
            return
        for tr in rows:
            if tr.find_parent("table") is not n:
                continue
            cells, imgs = [], []
            for c in tr.find_all(["th", "td"], recursive=False):
                raw = self.inline(c)
                for sub in c.find_all(["ul", "ol"]):
                    raw += BR + " ".join(norm(li.get_text(" ")) for li in sub.find_all("li"))
                bits = [norm(x) for x in raw.split(BR)]
                imgs += [b for b in bits if b.startswith("![")]
                cells.append(" ".join(b for b in bits if b and not b.startswith("![")).replace("|", "/"))
            if any(cells):
                self.emit(" | ".join(cells) if len([c for c in cells if c]) > 1 else next(c for c in cells if c))
            for im in imgs:
                self.emit(im)

    def walk(self, el):
        for n in el.children:
            if isinstance(n, Comment):
                continue
            if isinstance(n, NavigableString):
                self.buf.append(re.sub(r"\s+", " ", str(n)))
                continue
            if not isinstance(n, Tag):
                continue
            name = n.name
            if name in ("h1", "h2", "h3", "h4"):
                t = norm(n.get_text(" "))
                if t:
                    self.emit(("## " if name in ("h1", "h2") else "### ") + t)
            elif name in ("ul", "ol"):
                self.flush()
                self.lst(n)
            elif name == "table":
                self.table(n)
            elif name in ("h5", "h6", "dt", "summary"):
                self.emit(norm(n.get_text(" ")))
            elif name == "br":
                self.buf.append(BR)
            elif name == "img":
                self.buf.append(self.img(n))
            elif name not in BLOCKS:
                self.buf.append(self.inline(_One(n)))
            elif n.find(list(BLOCKS)) is not None:
                self.flush()
                self.walk(n)
                self.flush()
            else:
                self.flush()
                self.buf.append(self.inline(n))
                self.flush()
        self.flush()


class _One:
    def __init__(self, n):
        self.children = [n]


def to_lines(html: str, base: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    root = soup.body or soup
    for t in root.find_all(DROP):
        t.decompose()
    c = _Conv(base)
    c.walk(root)
    out: list[str] = []
    for ln in c.lines:
        ln = BULLET.sub("- ", ln)
        if out and ln == out[-1]:
            continue                                          # repeated line (often an image in a link and a cell)
        out.append(ln)
    return "\n".join(out).strip()


def article_content(art: dict, base: str) -> str:
    """Merge a ServiceNow article's template fields into one body. Falls back to the plain text field."""
    parts = dict(art.get("parts") or [])
    spec = TEMPLATE_PARTS.get(art.get("template") or "", [])
    chunks: list[str] = []
    for field, heading in spec:
        body = to_lines(parts.get(field) or "", base)
        if not body:
            continue
        if art.get("template") == "kb_template_faq" and field == "kb_question" and norm(body).rstrip("?") == norm(art.get("title") or "").rstrip("?"):
            continue                                          # the question is already the title
        chunks.append((f"## {heading}\n" if heading else "") + body)
    if not chunks:
        body = to_lines(art.get("text") or "", base)
        if body:
            chunks.append(body)
    return "\n".join(chunks).strip()
