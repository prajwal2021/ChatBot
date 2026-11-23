"""Find every page under a root URL and fetch it.

Discovery follows links from the root (and re-checks URLs we already know), staying on the same host and
under the root path. Files (PDF, Office, images, media, archives...) are listed in the inventory as skipped
but never downloaded.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import USER_AGENT
from .extract import extract, page_text, sha

FILE_EXT = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|csv|txt|rtf|zip|rar|7z|gz|png|jpe?g|gif|svg|webp|ico|bmp|tiff?|mp[34]|mov|avi|wmv|m4[av]|wav"
                      r"|css|js|json|xml|ics|vcf|eps|ai|psd|pub|exe|dmg)$", re.I)
INDEX = re.compile(r"/(index|default)\.(php|html?|aspx?)$", re.I)
JUNK_PATH = re.compile(r"/_|preview|/includes?/|/templates?/|/cgi-bin/|/google[0-9a-f]{12,}\.html$", re.I)
LEFTOVER = {"old", "test", "dev", "backup", "bak"}


def is_junk(path: str) -> bool:
    """Templates, previews and leftover copies such as old-index.php, index-test-dev.php or rfi-test.php.
    Only whole words count, and only in file names or a folder literally called test/old/dev, so real
    pages like /placement-test/ or /import-copy-course/ are kept."""
    if JUNK_PATH.search(path):
        return True
    parts = [x for x in path.lower().split("/") if x]
    if any(x in LEFTOVER for x in parts[:-1]) or (parts and "." not in parts[-1] and parts[-1] in LEFTOVER):
        return True
    if parts and "." in parts[-1]:
        tokens = re.split(r"[-_]", parts[-1].rsplit(".", 1)[0])
        return tokens[-1] in LEFTOVER or (("index" in tokens) and any(t in LEFTOVER for t in tokens)) or tokens == ["test"]
    return False


MAX_DEPTH = 8


def canon(url: str) -> str | None:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    path = re.sub(r"/{2,}", "/", p.path or "/")
    path = INDEX.sub("/", path)
    if path.endswith("/") and "." in path.rstrip("/").rsplit("/", 1)[-1] and len(path) > 1:
        path = path.rstrip("/")                      # /handbook.php/ is the same page as /handbook.php
    elif not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    local = p.hostname in ("localhost", "127.0.0.1")           # local test sites stay on http
    return urlunsplit((p.scheme if local else "https", p.netloc.lower(), path, "", ""))


@dataclass
class Fetched:
    url: str
    depth: int = 0
    kind: str = "page"            # page | file | skipped | missing | error
    http_status: int | None = None
    reason: str | None = None
    via: str = "link"             # link = reachable by clicking from the home page; sitemap = only in sitemap.xml;
                                  # known = tracked from an earlier crawl and re-checked directly
    data: dict | None = None      # extract() result for pages
    checks: list | None = None    # verification result (set by the pipeline)
    links: list[str] = field(default_factory=list)


def _in_scope(url: str, root: str) -> bool:
    u, r = urlsplit(url), urlsplit(root)
    return u.netloc == r.netloc and u.path.startswith(r.path)


def _fetch(client: httpx.Client, url: str, depth: int, root: str) -> Fetched:
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        return Fetched(url, depth, "error", None, f"{type(e).__name__}")
    final = canon(str(r.url)) or url
    if r.status_code in (404, 410):
        return Fetched(url, depth, "missing", r.status_code, "Page not found")
    if r.status_code >= 400:
        return Fetched(url, depth, "error", r.status_code, f"HTTP {r.status_code}")
    if final != url and not _in_scope(final, root):
        return Fetched(url, depth, "skipped", r.status_code, f"Redirects outside this site ({final})")
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype:
        return Fetched(url, depth, "file", r.status_code, f"Not a web page ({ctype.split(';')[0] or 'unknown type'})")
    data = extract(r.text, final)
    links = data.pop("links")
    f = Fetched(final, depth, "page", r.status_code, data=data, links=links)
    if not data["sections"]:
        f.kind, f.reason = "skipped", "No readable content on the page"
    return f


def sitemap_urls(client: httpx.Client, root: str) -> list[str]:
    """Page addresses listed in the site's sitemap.xml (following a sitemap index one level down)."""
    out: list[str] = []
    todo, seen = [root + "sitemap.xml"], set()
    while todo and len(seen) < 25:
        u = todo.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            r = client.get(u)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        for block, loc in re.findall(r"<(sitemap|url)>.*?<loc>\s*(.*?)\s*</loc>", r.text, flags=re.S | re.I):
            loc = loc.replace("&amp;", "&")
            (todo if block.lower() == "sitemap" else out).append(loc)
    return out


def _excluded(url: str, exclude: list[str]) -> bool:
    path = urlsplit(url).path.lower()
    return any(x.strip().lower() in path for x in exclude if x.strip())


def crawl(root_url: str, max_pages: int, known: list[str] | None = None, on_progress=None,
          exclude: list[str] | None = None, use_sitemap: bool = True, skip: set[str] | None = None) -> dict[str, Fetched]:
    """Two passes: follow links from the root (and re-check known pages), then pages only the sitemap lists."""
    root = canon(root_url)
    if not root:
        raise ValueError(f"Not a valid URL: {root_url}")
    exclude = exclude or []
    results: dict[str, Fetched] = {}
    queued: dict[str, int] = {}
    fetched = 0

    def consider(c: str | None, depth: int, via: str, seed: bool = False) -> tuple[str, int] | None:
        """Classify a newly seen URL; returns it when it should be fetched.
        `seed` = a page we already track, given to us directly: it may be a hand-added page outside the root.
        Links found ON any page never get that exemption, so the crawl cannot wander onto other websites."""
        if not c or c in queued or (not seed and not _in_scope(c, root)):
            return None
        queued[c] = depth
        if skip and c in skip:
            return None                                       # a person excluded this page: never fetched
        if seed:
            return c, depth
        path = urlsplit(c).path
        if _excluded(c, exclude):
            results[c] = Fetched(c, depth, "skipped", None, "Excluded by a rule on this source", via)
        elif FILE_EXT.search(path):
            results[c] = Fetched(c, depth, "file", None, "File, not a web page (" + c.rsplit(".", 1)[-1].lower() + ")", via)
        elif is_junk(path):
            results[c] = Fetched(c, depth, "skipped", None, "Template, test or leftover copy of a page", via)
        else:
            return c, depth
        return None

    with httpx.Client(follow_redirects=True, timeout=25, headers={"User-Agent": USER_AGENT}) as client, \
            ThreadPoolExecutor(max_workers=8) as pool:

        def run(frontier: list[tuple[str, int]], via: str) -> list[tuple[str, int]]:
            nonlocal fetched
            while frontier and fetched < max_pages:
                batch, frontier = frontier[: max_pages - fetched], frontier[max_pages - fetched:]
                nxt: list[tuple[str, int]] = []
                for f in pool.map(lambda x: _fetch(client, x[0], x[1], root), batch):
                    fetched += 1
                    f.via = via
                    if f.url in results and results[f.url].kind == "page":
                        continue                              # two URLs redirect to the same page
                    if _excluded(f.url, exclude):
                        f = Fetched(f.url, f.depth, "skipped", None, "Excluded by a rule on this source", via)
                    results[f.url] = f
                    queued.setdefault(f.url, f.depth)
                    if f.kind == "page" and f.depth < MAX_DEPTH:
                        for link in f.links:
                            item = consider(canon(link), f.depth + 1, via)
                            if item:
                                nxt.append(item)
                    if on_progress:
                        on_progress(fetched, len(queued), f.url)
                frontier += nxt
            return frontier

        left = run([x for x in [consider(root, 0, "link")] if x], "link")
        # pages we already track but could not reach by clicking from the home page: re-check them as "known"
        left += run([x for x in (consider(k, 1, "known", seed=True) for k in known or []) if x], "known")
        if use_sitemap:
            extra = [x for x in (consider(canon(u), 1, "sitemap") for u in sitemap_urls(client, root)) if x]
            left += run(extra, "sitemap")
    for url, depth in left:                                   # found but over the page limit
        results.setdefault(url, Fetched(url, depth, "skipped", None, f"Over the page limit ({max_pages}) for this source"))
    attach_contacts(results)
    return results


def original_first(f: Fetched) -> tuple:
    """Sort key: among pages with the same content, the one people reach by clicking, nearest the home page."""
    return f.via != "link", f.depth, len(f.url), f.url


def attach_contacts(results: dict[str, Fetched]) -> None:
    """Each distinct contact block becomes a section of only the first page showing it; the others drop it.
    shortcut: owner is picked per crawl, so if that page fails to load the block moves to the next page for one
    run (one new + one removal proposal); make ownership sticky in the database if that churn shows up."""
    taken: set[str] = set()
    for f in sorted((f for f in results.values() if f.kind == "page"), key=original_first):
        c = f.data.pop("contact", None)
        if c and c["hash"] not in taken:
            taken.add(c["hash"])
            f.data["sections"].append(c)
            f.data["text"] = page_text(f.data["sections"])
            f.data["hash"] = sha(f.data["text"])
