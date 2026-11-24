"""Reviewer accounts: password hashing and the command that creates them.

    python -m app.users add "Jane Doe"     # asks for the password; on an existing name, resets it
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import secrets
import sys

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import LoginSession, User, now

MIN_PASSWORD = 8
# scrypt cost: ~50 ms per hash, slow enough to make guessing billions of passwords impractical
N, R, P = 2**14, 8, 1


def hash_password(pw: str) -> str:
    """Return a one-way, salted hash in the form 'scrypt$<salt hex>$<hash hex>'."""
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    """True if `pw` produces `stored`. A malformed stored value is a mismatch, not an error."""
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=N, r=R, p=P)
    except ValueError:
        return False
    return hmac.compare_digest(h, bytes.fromhex(hash_hex))  # same time whether close or not


def token_hash(token: str) -> str:
    """The session token as stored in the database (sha256 hex): the raw token only ever lives in the cookie."""
    return hashlib.sha256(token.encode()).hexdigest()


def find_user(db: Session, name: str) -> User | None:
    """Look up a user by name, ignoring case ('jane doe' finds 'Jane Doe')."""
    return db.scalar(select(User).where(func.lower(User.name) == name.strip().lower()))


def current_user(kb_session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    """The signed-in user, from the session cookie. 401 when missing, unknown or expired."""
    s = db.get(LoginSession, token_hash(kb_session)) if kb_session else None
    if s and s.expires_at < now():
        db.delete(s)
        db.commit()
        s = None
    user = db.get(User, s.user_id) if s else None
    if not user:
        raise HTTPException(401, "Please sign in")
    return user


def actor(user: User = Depends(current_user)) -> str:
    """Who did it, for History: the signed-in name (FastAPI runs current_user once per request)."""
    return user.name


def add_user(name: str) -> None:
    """Create the user, or reset the password of an existing one. Prompts for the password twice."""
    from .db import Base, SessionLocal, engine  # only the command needs these

    name = name.strip()
    if not name or len(name) > 80:
        sys.exit("Name must be 1 to 80 characters.")
    pw = getpass.getpass("Password: ")
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"Password must be at least {MIN_PASSWORD} characters.")
    if getpass.getpass("Again:    ") != pw:
        sys.exit("Passwords don't match.")

    Base.metadata.create_all(engine, tables=[User.__table__, LoginSession.__table__])  # works before the API first starts
    with SessionLocal() as db:
        user = find_user(db, name)
        if user:
            user.password_hash = hash_password(pw)
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))  # signed out everywhere
            msg = f"Password reset for {user.name}"
        else:
            db.add(User(name=name, password_hash=hash_password(pw)))
            msg = f"Added {name}"
        db.commit()
    print(msg)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m app.users")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add", help="add a user or reset their password").add_argument("name")
    add_user(ap.parse_args().name)
