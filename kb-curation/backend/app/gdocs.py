"""Push a published .docx into a Google Doc (Drive converts it in place, so the Doc keeps its URL and sharing)."""
from __future__ import annotations

import re

from .config import GOOGLE_SERVICE_ACCOUNT_FILE

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def configured() -> bool:
    return bool(GOOGLE_SERVICE_ACCOUNT_FILE)


def doc_id(url: str | None) -> str | None:
    m = re.search(r"/document/d/([A-Za-z0-9_-]{20,})", url or "")
    return m.group(1) if m else None


def service_email() -> str | None:
    if not configured():
        return None
    try:
        import json
        return json.load(open(GOOGLE_SERVICE_ACCOUNT_FILE)).get("client_email")
    except Exception:                                         # noqa: BLE001
        return None


def push(url: str, data: bytes) -> None:
    if not configured():
        raise RuntimeError("Google is not connected: set GOOGLE_SERVICE_ACCOUNT_FILE in backend/.env.")
    fid = doc_id(url)
    if not fid:
        raise RuntimeError("That link is not a Google Doc link.")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/drive"])
    r = AuthorizedSession(creds).patch(
        f"https://www.googleapis.com/upload/drive/v3/files/{fid}?uploadType=media&supportsAllDrives=true",
        data=data, headers={"Content-Type": DOCX}, timeout=120)
    if r.status_code == 404:
        raise RuntimeError(f"Google could not find the Doc. Share it with {service_email()} as Editor.")
    if r.status_code >= 400:
        raise RuntimeError(f"Google rejected the update ({r.status_code}): {r.text[:300]}")
