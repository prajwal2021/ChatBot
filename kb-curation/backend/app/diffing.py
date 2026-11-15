"""Line diffs in the shape the UI renders (GitHub style)."""
from __future__ import annotations

import difflib


def line_diff(old: str, new: str, context: int = 2, limit: int = 600) -> tuple[list[dict], int, int]:
    a, b = (old or "").splitlines(), (new or "").splitlines()
    out: list[dict] = []
    added = removed = 0
    for line in difflib.unified_diff(a, b, n=context, lineterm=""):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            out.append({"t": "@", "s": line})
        elif line.startswith("+"):
            added += 1
            out.append({"t": "+", "s": line[1:]})
        elif line.startswith("-"):
            removed += 1
            out.append({"t": "-", "s": line[1:]})
        else:
            out.append({"t": " ", "s": line[1:]})
    if len(out) > limit:
        out = out[:limit] + [{"t": "@", "s": f"… {len(out) - limit} more lines not shown"}]
    return out, added, removed


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "", autojunk=False).quick_ratio()
