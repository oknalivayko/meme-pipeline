import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memes (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    post_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    year_month TEXT NOT NULL,
    text TEXT,
    photo_path TEXT,
    reactions TEXT,
    total_reactions INTEGER NOT NULL DEFAULT 0,
    laugh_reactions INTEGER NOT NULL DEFAULT 0,
    channel_score REAL NOT NULL DEFAULT 0,
    laugh_score REAL NOT NULL DEFAULT 0,
    global_score REAL NOT NULL DEFAULT 0,
    UNIQUE (source, post_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    meme_id INTEGER NOT NULL REFERENCES memes (id),
    target TEXT NOT NULL,
    decision TEXT NOT NULL,
    image_hash TEXT,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (meme_id, target)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT,
    image_path TEXT,
    source_meme_id INTEGER,
    publish_at TEXT,
    sent INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memes_rank ON memes (source, channel_score);
CREATE INDEX IF NOT EXISTS idx_posts_queue ON posts (target, kind, sent, id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
