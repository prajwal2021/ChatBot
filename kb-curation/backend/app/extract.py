"""Turn a page's HTML into clean sections (one per heading) that reviewers and the chatbot can read.

Body format, one item per line: sentences, "- " bullets, "1. " ordered steps, table rows as "a | b | c",
links as markdown [text](url). Text is copied from the page as written; nothing is rewritten.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

DROP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "form", "iframe", "svg", "button", "select", "template"]
DROP_CLASS = re.compile(r"footer-copyright|breadcrumb|swiper|carousel|slider|social|skip-|cookie|sr-only|visually-hidden|modal|pagination", re.I)
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
BLOCKS = {"p", "div", "section", "article", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
          "dl", "dt", "dd", "figure", "figcaption", "details", "summary", "main", "address", "pre", "hr", "li", "tr"}
# lines that change on every visit and carry no knowledge
NOISE = re.compile(r"^(last (updated|modified|reviewed)\b.*|©.*|copyright ©?.*\d{4}.*|page (updated|last updated)\b.*|back to top|skip to .*)$", re.I)


BR = "\x00"      # marks a real <br>; newlines in the HTML source are just spaces


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def sha(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(norm(p or "") for p in parts).encode()).hexdigest()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80] or "section"


def _inline(el, base: str) -> str:
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
        elif n.name in ("ul", "ol", "table"):
            continue
        elif n.name == "a":
            text = norm(n.get_text(" "))
            href = (n.get("href") or "").strip()
            if not text:
                continue
            if href.lower().startswith("mailto:"):
                addr = href[7:].split("?")[0]
                out.append(text if addr.lower() in text.lower() else f"{text} ({addr})")
            elif not href or href.startswith("#") or href.lower().startswith(("javascript", "tel:")):
                out.append(text)
            else:
                out.append(f"[{text}]({urljoin(base, href)})")
        else:
            out.append(_inline(n, base))
    return "".join(out)


def _lines(text: str) -> list[str]:
    return [t for t in (norm(x).replace(")[", ") · [") for x in text.split(BR)) if t]


class _Builder:
    def __init__(self, base: str, title: str):
        self.base = base
        self.sections: list[dict] = [{"title": title, "level": 1, "lines": []}]
        self.buf: list[str] = []

    def flush(self):
        if self.buf:
            self.sections[-1]["lines"] += _lines("".join(self.buf))
            self.buf = []

    def emit(self, line: str):
        self.flush()
        if line:
            self.sections[-1]["lines"].append(line)

    def lst(self, el: Tag, depth: int = 0):
        i = 0
        for li in el.find_all("li", recursive=False):
            i += 1
            text = norm(_inline(li, self.base).replace(BR, " ")).replace(")[", ") · [")
            if text:
                self.emit("  " * depth + (f"{i}. " if el.name == "ol" else "- ") + text)
            for sub in li.find_all(["ul", "ol"], recursive=False):
                self.lst(sub, depth + 1)

    def walk(self, el: Tag):
        for n in el.children:
            if isinstance(n, Comment):
                continue
            if isinstance(n, NavigableString):
                self.buf.append(re.sub(r"\s+", " ", str(n)))
                continue
            if not isinstance(n, Tag):
                continue
            name = n.name
            if name in HEADINGS:
                self.flush()
                t = norm(n.get_text(" "))
                if t:
                    self.sections.append({"title": t, "level": HEADINGS[name], "lines": []})
            elif name in ("ul", "ol"):
                self.flush()
                self.lst(n)
            elif name == "table":
                self.flush()
                for tr in n.find_all("tr"):
                    cells = [norm(_inline(c, self.base).replace(BR, " ")) for c in tr.find_all(["th", "td"])]
                    if any(cells):
                        self.emit(" | ".join(cells))
            elif name in ("h5", "h6", "dt", "summary"):
                self.emit(norm(n.get_text(" ")))
            elif name == "br":
                self.buf.append(BR)
            elif name not in BLOCKS:                       # inline element: keep it on the current line
                self.buf.append(_inline_wrap(n, self.base))
            elif n.find(list(BLOCKS)) is not None:
                self.flush()
                self.walk(n)
                self.flush()
            else:
                self.flush()
                for line in _lines(_inline(n, self.base)):
                    self.emit(line)
        self.flush()


class _One:
    """Lets _inline() treat a single node as the only child of a parent."""
    def __init__(self, n):
        self.children = [n]


def _inline_wrap(n: Tag, base: str) -> str:
    return _inline(_One(n), base)


def page_links(soup: BeautifulSoup, base: str) -> list[str]:
    return [urljoin(base, a["href"].strip()) for a in soup.find_all("a", href=True)
            if not a["href"].strip().lower().startswith(("#", "mailto:", "tel:", "javascript"))]


def _clean(raw: list[dict]) -> list[dict]:
    """Drop noise lines and headings with nothing under them; give each section a unique key and a hash."""
    sections, seen = [], {}
    for s in raw:
        lines = [x for x in s["lines"] if not NOISE.match(x)]
        body = "\n".join(lines)
        if len(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)) < 25:      # heading with nothing under it
            continue
        k = slug(s["title"])
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1:
            k = f"{k}-{seen[k]}"
        sections.append({"key": k, "title": s["title"], "level": s["level"], "content": body, "hash": sha(s["title"], body)})
    return sections


def page_text(sections: list[dict]) -> str:
    return "\n\n".join(f"## {s['title']}\n{s['content']}" for s in sections)


def extract(html: str, url: str) -> dict:
    """The site-wide contact block (.l-contact) repeats on most pages, so it is returned apart as "contact"
    (not in sections/text); crawler.attach_contacts() gives each distinct block to one page only."""
    soup = BeautifulSoup(html, "lxml")
    links = page_links(soup, url)
    raw_title = norm(soup.title.get_text()) if soup.title else ""
    main = soup.find("main") or soup.find(id=re.compile(r"main.?content|^content$", re.I)) or soup.body or soup
    for t in main.find_all(DROP_TAGS):
        t.decompose()
    for t in main.find_all(class_=DROP_CLASS):
        if not t.decomposed:
            t.decompose()
    contact = None
    block = main.find(class_="l-contact")
    if block:
        block.extract()                    # taken out before the page title is picked: it can hold an <h1>
        for h in block.find_all(list(HEADINGS)):
            h.name = "p"                   # the block's own title must not split it into sections
        cb = _Builder(url, "Contact information")
        cb.walk(block)
        contact = next(({**s, "key": "site-contact-block"} for s in _clean(cb.sections)), None)
    h1 = main.find("h1")
    title = norm(h1.get_text(" ")) if h1 and norm(h1.get_text(" ")) else re.split(r"\s+[|–—]\s+", raw_title)[0]
    title = title or url
    b = _Builder(url, title)
    b.walk(main)
    sections = _clean(b.sections)
    text = page_text(sections)
    return {"title": title, "sections": sections, "links": links, "text": text, "hash": sha(text), "contact": contact}
