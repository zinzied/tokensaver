#!/usr/bin/env python3
"""Token Saver SQLite FTS5 Index — inspired by ctxrs/ctx's local search index.

Replaces JSON file storage with a single SQLite database for fast
full-text search, SQL queries, and structured compression history.
"""

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".config" / "opencode" / "compress" / "index.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    model           TEXT,
    provider        TEXT,
    task            TEXT,
    total_events    INTEGER DEFAULT 0,
    total_saved     INTEGER DEFAULT 0,
    total_raw       INTEGER DEFAULT 0,
    compression_pct REAL DEFAULT 0.0,
    metadata        TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id                 TEXT PRIMARY KEY,
    session_id         TEXT REFERENCES sessions(id),
    kind               TEXT NOT NULL,
    description        TEXT NOT NULL,
    raw_tokens         INTEGER DEFAULT 0,
    compressed_tokens  INTEGER DEFAULT 0,
    saved_tokens       INTEGER DEFAULT 0,
    compression_pct    REAL DEFAULT 0.0,
    metadata           TEXT,
    timestamp          TEXT NOT NULL,
    hash               TEXT,
    prev_hash          TEXT
);

CREATE TABLE IF NOT EXISTS files_touched (
    event_id        TEXT REFERENCES events(id),
    path            TEXT NOT NULL,
    mode            TEXT,
    compression_pct REAL DEFAULT 0.0,
    cached          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proxy_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT,
    model       TEXT,
    cost_level  TEXT,
    raw_tokens  INTEGER DEFAULT 0,
    saved_tokens INTEGER DEFAULT 0,
    timestamp   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache_entries (
    key             TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    mode            TEXT,
    raw_tokens      INTEGER DEFAULT 0,
    compressed_tokens INTEGER DEFAULT 0,
    saved_tokens    INTEGER DEFAULT 0,
    compression_pct REAL DEFAULT 0.0,
    cached_at       REAL NOT NULL,
    hit_count       INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    description, kind, metadata,
    content=events, content_rowid=rowid
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    path,
    content=files_touched, content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, description, kind, metadata)
    VALUES (new.rowid, new.description, new.kind, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, description, kind, metadata)
    VALUES ('delete', old.rowid, old.description, old.kind, old.metadata);
END;

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files_touched BEGIN
    INSERT INTO files_fts(rowid, path)
    VALUES (new.rowid, new.path);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files_touched BEGIN
    INSERT INTO files_fts(files_fts, rowid, path)
    VALUES ('delete', old.rowid, old.path);
END;

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_proxy_model ON proxy_requests(model);
CREATE INDEX IF NOT EXISTS idx_proxy_timestamp ON proxy_requests(timestamp);
CREATE INDEX IF NOT EXISTS idx_cache_path ON cache_entries(path);
"""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _ensure_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables and indexes if they don't exist."""
    conn = _connect()
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()
    conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row else {}


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def start_session(model: str = "", provider: str = "", task: str = "") -> str:
    """Create a new compression session and return its ID."""
    session_id = f"ses_{int(time.time() * 1000):x}_{os.getpid()}"
    conn = _connect()
    conn.execute(
        """INSERT INTO sessions (id, started_at, model, provider, task)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, datetime.now().isoformat(), model, provider, task),
    )
    conn.commit()
    conn.close()
    return session_id


def end_session(session_id: str):
    """Finalize a session with aggregate stats."""
    conn = _connect()
    row = conn.execute(
        """SELECT COUNT(*) as cnt, COALESCE(SUM(saved_tokens),0) as saved,
                  COALESCE(SUM(raw_tokens),0) as raw
           FROM events WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    if row:
        pct = (row["saved"] / row["raw"] * 100) if row["raw"] > 0 else 0
        conn.execute(
            """UPDATE sessions SET ended_at=?, total_events=?, total_saved=?,
               total_raw=?, compression_pct=? WHERE id=?""",
            (datetime.now().isoformat(), row["cnt"], row["saved"], row["raw"], pct, session_id),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------

def log_event(
    kind: str,
    description: str,
    raw_tokens: int = 0,
    compressed_tokens: int = 0,
    session_id: str | None = None,
    metadata: dict | None = None,
    files: list[dict] | None = None,
) -> str:
    """Log a compression event. Returns event ID."""
    saved = max(0, raw_tokens - compressed_tokens)
    pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0
    event_id = f"evt_{int(time.time() * 1000):x}_{hashlib.md5(description.encode()).hexdigest()[:8]}"
    ts = datetime.now().isoformat()

    conn = _connect()

    # Get previous hash for chain
    prev = conn.execute(
        "SELECT hash FROM events ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    prev_hash = prev["hash"] if prev else "0" * 64

    meta_json = json.dumps(metadata or {})
    entry_data = f"{event_id}{kind}{description}{raw_tokens}{compressed_tokens}{ts}{prev_hash}"
    event_hash = hashlib.sha256(entry_data.encode()).hexdigest()

    conn.execute(
        """INSERT INTO events
           (id, session_id, kind, description, raw_tokens, compressed_tokens,
            saved_tokens, compression_pct, metadata, timestamp, hash, prev_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, session_id, kind, description, raw_tokens, compressed_tokens,
         saved, pct, meta_json, ts, event_hash, prev_hash),
    )

    # Log touched files
    if files:
        for f in files:
            conn.execute(
                """INSERT INTO files_touched (event_id, path, mode, compression_pct, cached)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, f.get("path", ""), f.get("mode", ""),
                 f.get("compression_pct", 0), 1 if f.get("cached") else 0),
            )

    conn.commit()
    conn.close()
    return event_id


def log_proxy_request(path: str, model: str, raw_tokens: int, saved_tokens: int, cost_level: str = ""):
    """Log a proxy request."""
    conn = _connect()
    conn.execute(
        """INSERT INTO proxy_requests (path, model, cost_level, raw_tokens, saved_tokens, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (path, model, cost_level, raw_tokens, saved_tokens, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def log_cache_hit(path: str, mode: str, raw_tokens: int):
    """Record a cache hit (re-read costs ~13 tokens)."""
    key = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]
    conn = _connect()
    existing = conn.execute(
        "SELECT * FROM cache_entries WHERE key = ?", (key,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE cache_entries SET hit_count = hit_count + 1 WHERE key = ?", (key,)
        )
    else:
        conn.execute(
            """INSERT INTO cache_entries
               (key, path, mode, raw_tokens, compressed_tokens, saved_tokens,
                compression_pct, cached_at, hit_count)
               VALUES (?, ?, ?, ?, 13, ?, ?, ?, 1)""",
            (key, path, mode, raw_tokens, max(0, raw_tokens - 13),
             (1 - 13 / raw_tokens) * 100 if raw_tokens > 0 else 0, time.time()),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Search (FTS5)
# ---------------------------------------------------------------------------

def search_events(query: str, limit: int = 20, kind: str | None = None,
                  since: str | None = None) -> list[dict]:
    """Full-text search across events."""
    conn = _connect()
    sql = """
        SELECT e.id, e.session_id, e.kind, e.description,
               e.saved_tokens, e.compression_pct, e.timestamp, e.metadata
        FROM events e
        JOIN events_fts f ON e.rowid = f.rowid
        WHERE events_fts MATCH ?
    """
    params: list = [query]
    if kind:
        sql += " AND e.kind = ?"
        params.append(kind)
    if since:
        dt = datetime.now() - timedelta(seconds=_parse_duration(since))
        sql += " AND e.timestamp >= ?"
        params.append(dt.isoformat())
    sql += " ORDER BY e.timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def search_files(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across touched files."""
    conn = _connect()
    rows = conn.execute(
        """SELECT f.event_id, f.path, f.mode, f.compression_pct, f.cached,
                  e.description, e.timestamp
           FROM files_touched f
           JOIN files_fts ft ON f.rowid = ft.rowid
           JOIN events e ON f.event_id = e.id
           WHERE files_fts MATCH ?
           ORDER BY e.timestamp DESC LIMIT ?""",
        (query, limit),
    ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def sql_query(query: str) -> list[dict]:
    """Execute a read-only SQL query against the index."""
    conn = _connect()
    # Safety: only allow SELECT
    stripped = query.strip().upper()
    if not stripped.startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed")
    rows = conn.execute(query).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def stats_summary() -> dict:
    """Aggregate statistics across all events, sessions, proxy, and cache."""
    conn = _connect()

    event_stats = conn.execute(
        """SELECT COUNT(*) as total_events,
                  COALESCE(SUM(saved_tokens),0) as total_saved,
                  COALESCE(SUM(raw_tokens),0) as total_raw,
                  COALESCE(AVG(compression_pct),0) as avg_compression
           FROM events"""
    ).fetchone()

    session_stats = conn.execute(
        "SELECT COUNT(*) as total_sessions FROM sessions"
    ).fetchone()

    by_kind = _rows_to_dicts(conn.execute(
        """SELECT kind, COUNT(*) as count,
                  COALESCE(SUM(saved_tokens),0) as saved,
                  COALESCE(SUM(raw_tokens),0) as raw
           FROM events GROUP BY kind ORDER BY saved DESC"""
    ).fetchall())

    file_stats = conn.execute(
        """SELECT COUNT(*) as total_files,
                  COUNT(DISTINCT path) as unique_files,
                  COALESCE(AVG(compression_pct),0) as avg_compression
           FROM files_touched"""
    ).fetchone()

    proxy_stats = conn.execute(
        """SELECT COUNT(*) as total_requests,
                  COALESCE(SUM(saved_tokens),0) as total_saved,
                  COALESCE(AVG(saved_tokens),0) as avg_saved
           FROM proxy_requests"""
    ).fetchone()

    cache_stats = conn.execute(
        """SELECT COUNT(*) as entries,
                  COALESCE(SUM(hit_count),0) as total_hits,
                  COALESCE(AVG(compression_pct),0) as avg_compression
           FROM cache_entries"""
    ).fetchone()

    recent_events = _rows_to_dicts(conn.execute(
        """SELECT id, kind, description, saved_tokens, compression_pct, timestamp
           FROM events ORDER BY timestamp DESC LIMIT 5"""
    ).fetchall())

    conn.close()

    total_raw = event_stats["total_raw"]
    total_saved = event_stats["total_saved"]

    return {
        "schema_version": SCHEMA_VERSION,
        "db_path": str(DB_PATH),
        "sessions": _row_to_dict(session_stats),
        "events": {
            "total": event_stats["total_events"],
            "total_saved_tokens": total_saved,
            "total_raw_tokens": total_raw,
            "compression_pct": round(total_saved / total_raw * 100, 1) if total_raw > 0 else 0,
            "avg_compression_pct": round(event_stats["avg_compression"], 1),
            "by_kind": by_kind,
        },
        "files": _row_to_dict(file_stats),
        "proxy": _row_to_dict(proxy_stats),
        "cache": _row_to_dict(cache_stats),
        "recent_events": recent_events,
    }


# ---------------------------------------------------------------------------
# Import from legacy JSON files
# ---------------------------------------------------------------------------

def import_from_legacy():
    """Import data from existing JSON files into the SQLite index."""
    compress_dir = DB_PATH.parent
    imported = 0

    # Import savings ledger
    ledger_path = compress_dir / "savings_ledger.json"
    if ledger_path.exists():
        try:
            entries = json.loads(ledger_path.read_text("utf-8"))
            for entry in entries:
                log_event(
                    kind=entry.get("kind", "unknown"),
                    description=entry.get("description", ""),
                    raw_tokens=entry.get("raw_tokens", 0),
                    compressed_tokens=entry.get("compressed_tokens", 0),
                    metadata=entry.get("metadata"),
                )
                imported += 1
        except Exception:
            pass

    # Import proxy history
    proxy_path = compress_dir / "proxy.json"
    if proxy_path.exists():
        try:
            proxy_data = json.loads(proxy_path.read_text("utf-8"))
            for req in proxy_data.get("history", []):
                log_proxy_request(
                    path=req.get("path", ""),
                    model="",
                    raw_tokens=0,
                    saved_tokens=req.get("saved_tokens", 0),
                )
                imported += 1
        except Exception:
            pass

    # Import cache entries
    cache_dir = compress_dir / "cache"
    if cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text("utf-8"))
                log_cache_hit(
                    path=data.get("path", ""),
                    mode=data.get("mode", ""),
                    raw_tokens=data.get("compressed_tokens", 0) + data.get("saved_tokens", 0),
                )
                imported += 1
            except Exception:
                pass

    return imported


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_duration(s: str) -> int:
    """Parse '30d', '7d', '24h', '60m' into seconds."""
    s = s.strip().lower()
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    elif s.endswith("h"):
        return int(s[:-1]) * 3600
    elif s.endswith("m"):
        return int(s[:-1]) * 60
    return int(s)


def verify_ledger() -> dict:
    """Verify the hash chain integrity of all events."""
    conn = _connect()
    events = _rows_to_dicts(conn.execute(
        "SELECT * FROM events ORDER BY rowid"
    ).fetchall())
    conn.close()

    errors = []
    for i, event in enumerate(events):
        expected_prev = events[i - 1]["hash"] if i > 0 else "0" * 64
        if event.get("prev_hash", "") != expected_prev:
            errors.append(f"Event {event['id']}: hash chain broken at position {i}")

    return {
        "valid": len(errors) == 0,
        "total_events": len(events),
        "errors": errors,
    }


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
    print(f"Imported {import_from_legacy()} legacy entries")
    print(json.dumps(stats_summary(), indent=2))
