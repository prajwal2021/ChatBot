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
SN_MODEL = os.getenv("KB_SN_MODEL", "gpt-4.1")                  # reconciles ServiceNow articles with linked pages
SN_IMPORT_TOKEN = os.getenv("SN_IMPORT_TOKEN", "")                # one-time import from the browser; empty = import off
SN_INSTANCE = os.getenv("SN_INSTANCE", "https://support.k12.ttu.edu")
PUBLIC_API_BASE = os.getenv("KB_PUBLIC_API_BASE", "")              # absolute API URL used in exports, e.g. https://host/kb-curation-api
EXTRA_ORIGINS = [o.strip() for o in os.getenv("KB_EXTRA_ORIGINS", "").split(",") if o.strip()]
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
USER_AGENT = "TTU-KB-Curation/1.0 (internal knowledge base crawler)"
