"""Central configuration for the Workload Management System.

Every setting can be overridden with an environment variable, but the defaults
are chosen so the project runs immediately with zero setup (SQLite + mock APIs).
"""
import os


def _load_dotenv() -> None:
    """Minimal .env loader (avoids a python-dotenv dependency). Reads KEY=VALUE
    lines from a .env file in the project root into the environment, without
    overriding variables that are already set."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()

# --- Database backend -------------------------------------------------------
# "sqlite" (default): zero-install, a real relational/ACID database in a file.
# "mysql":  for submission. Set the MYSQL_* vars and run db/schema_mysql.sql.
DB_BACKEND = os.environ.get("WMS_DB_BACKEND", "sqlite")

SQLITE_PATH = os.environ.get("WMS_SQLITE_PATH", "wms.db")

MYSQL = {
    "host": os.environ.get("WMS_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("WMS_MYSQL_PORT", "3306")),
    "user": os.environ.get("WMS_MYSQL_USER", "root"),
    "password": os.environ.get("WMS_MYSQL_PASSWORD", ""),
    "database": os.environ.get("WMS_MYSQL_DB", "wms"),
}

# --- OS layer / engine ------------------------------------------------------
# 1 worker == a single CPU, which makes the scheduling order clearly visible.
NUM_WORKERS = int(os.environ.get("WMS_WORKERS", "1"))

# Pooled DB connections handed out by the Resource Manager.
DB_POOL_SIZE = int(os.environ.get("WMS_DB_POOL", "4"))

# Round Robin time quantum (milliseconds).
RR_QUANTUM_MS = int(os.environ.get("WMS_QUANTUM_MS", "150"))

# Rate limit for the (mock or real) external music/AI APIs, requests per minute.
API_RATE_PER_MIN = int(os.environ.get("WMS_API_RATE", "240"))

# --- AI + music providers ---------------------------------------------------
# "auto" (default): use the real provider when its credentials are present,
#                   otherwise fall back to the offline mock. Decided per provider.
# "mock": always mock.   "real": force real (errors if creds missing).
PROVIDER_MODE = os.environ.get("WMS_PROVIDERS", "auto")

# Real Spotify — client-credentials flow (search only; NO user login, NO
# Premium required). Put these in a .env file (see .env.example).
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Real Gemini — needs a (free) API key from https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# Number of tracks each generated playlist contains.
PLAYLIST_SIZE = int(os.environ.get("WMS_PLAYLIST_SIZE", "10"))
