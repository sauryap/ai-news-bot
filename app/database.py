"""
SQLite persistence layer.

Keeps things intentionally simple: one module owns the schema and a handful
of small, direct functions for reading/writing. No ORM.
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from app import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    description TEXT,
    category TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles(content_hash);
CREATE INDEX IF NOT EXISTS idx_articles_processed ON articles(processed);

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT,
    why_it_matters TEXT,
    importance INTEGER,
    category TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story_articles (
    story_id INTEGER NOT NULL REFERENCES stories(id),
    article_id INTEGER REFERENCES articles(id),
    source_url TEXT,
    PRIMARY KEY (story_id, article_id, source_url)
);

CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT,
    raw_json TEXT NOT NULL,
    message_text TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the database file and tables if they don't already exist."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database ready at %s", config.DATABASE_PATH)


def insert_article(article) -> Optional[int]:
    """Insert an article. Returns the new row id, or None if it was a duplicate."""
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO articles
                    (title, url, source, author, published_at, description,
                     category, content_hash, created_at, processed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    article.title,
                    article.url,
                    article.source,
                    article.author,
                    article.published_at,
                    article.description,
                    article.category,
                    article.content_hash,
                    _utcnow_iso(),
                ),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate URL - already have this article.
            return None


def content_hash_exists(content_hash: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM articles WHERE content_hash = ? LIMIT 1", (content_hash,)
        ).fetchone()
        return row is not None


def url_exists(url: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM articles WHERE url = ? LIMIT 1", (url,)).fetchone()
        return row is not None


def get_article_id_by_url(url: str) -> Optional[int]:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM articles WHERE url = ? LIMIT 1", (url,)).fetchone()
        return row["id"] if row else None


def get_unprocessed_articles() -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM articles WHERE processed = 0 ORDER BY created_at DESC"
        ).fetchall()


def get_recent_articles(limit: int = 500) -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM articles ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()


def mark_articles_processed(article_ids: Iterable[int]) -> None:
    ids = list(article_ids)
    if not ids:
        return
    with get_connection() as conn:
        conn.executemany(
            "UPDATE articles SET processed = 1 WHERE id = ?", [(i,) for i in ids]
        )


def insert_story(story, article_ids: Iterable[Optional[int]], source_urls: Iterable[str]) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO stories (title, summary, why_it_matters, importance, category, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                story.title,
                story.summary,
                story.why_it_matters,
                story.importance,
                story.category,
                _utcnow_iso(),
            ),
        )
        story_id = cur.lastrowid

        article_ids = list(article_ids) or [None]
        urls = list(source_urls) or [""]
        # Pair up as best as possible; fall back to storing urls without a
        # matched article_id when we couldn't resolve one locally.
        rows = []
        max_len = max(len(article_ids), len(urls))
        for i in range(max_len):
            aid = article_ids[i] if i < len(article_ids) else None
            url = urls[i] if i < len(urls) else ""
            rows.append((story_id, aid, url))
        conn.executemany(
            "INSERT OR IGNORE INTO story_articles (story_id, article_id, source_url) VALUES (?, ?, ?)",
            rows,
        )
        return story_id


def save_briefing(title: str, raw: dict, message_text: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO briefings (created_at, title, raw_json, message_text, sent) VALUES (?, ?, ?, ?, 0)",
            (_utcnow_iso(), title, json.dumps(raw, ensure_ascii=False), message_text),
        )
        return cur.lastrowid


def get_latest_briefing() -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()


def mark_briefing_sent(briefing_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE briefings SET sent = 1 WHERE id = ?", (briefing_id,))
