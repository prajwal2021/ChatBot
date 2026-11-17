"""python -m app.scope_import <chatbot key> <file.pdf|file.txt>  - load the SME's KB document as the scope for a chatbot."""
import sys

from sqlalchemy import select

from . import scope
from .db import SessionLocal
from .models import Chatbot

if __name__ == "__main__":
    key, path = sys.argv[1], sys.argv[2]
    db = SessionLocal()
    bot = db.scalar(select(Chatbot).where(Chatbot.key == key))
    text = scope.pdf_text(path) if path.lower().endswith(".pdf") else open(path, encoding="utf-8").read()
    print(scope.import_topics(db, bot, text))
    db.close()
    print(scope.match(bot.id))
