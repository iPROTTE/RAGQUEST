import os, sqlite3, threading
from .config import DB_PATH

lock = threading.Lock()   # serializa escritas

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL, title TEXT NOT NULL,
  tipo TEXT NOT NULL DEFAULT 'manual', setor TEXT, source_url TEXT,
  content_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS doc_slug ON documents(slug, active);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page INTEGER, content TEXT NOT NULL, embedding BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS chunk_doc ON chunks(document_id);
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, size INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content, tokenize='unicode61 remove_diacritics 2');
"""

def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        c.execute("PRAGMA journal_mode=WAL")
