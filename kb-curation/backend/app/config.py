import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://localhost:5432/kb_curation")
WEB_ORIGIN = os.getenv("WEB_ORIGIN", "http://localhost:3010")
DATA_DIR = Path(os.getenv("KB_DATA_DIR", ROOT / "data"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CATEGORIZE_MODEL = os.getenv("KB_CATEGORIZE_MODEL", "gpt-4o-mini")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
USER_AGENT = "TTU-KB-Curation/1.0 (internal knowledge base crawler)"
