"""SQLite definitions database -- symbol -> file:line mappings."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    line            INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    containing_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbol ON definitions(symbol);
CREATE INDEX IF NOT EXISTS idx_source ON definitions(source);
CREATE INDEX IF NOT EXISTS idx_qualified_name ON definitions(qualified_name);
"""


def _upgrade_db(conn: sqlite3.Connection) -> None:
    """Add missing columns to the definitions table (forward-only migrations)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(definitions)")}
    migrations = {
        "source": "ALTER TABLE definitions ADD COLUMN source TEXT NOT NULL DEFAULT ''",
        "containing_type": "ALTER TABLE definitions ADD COLUMN containing_type TEXT",
    }
    for col, stmt in migrations.items():
        if col not in existing:
            conn.execute(stmt)
    conn.commit()


def create_db(db_path: Path) -> sqlite3.Connection:
    """Create the definitions database and return a connection."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _upgrade_db(conn)
    conn.commit()
    return conn


def clear_source(conn: sqlite3.Connection, source: str) -> None:
    """Delete all definitions for a given source."""
    conn.execute("DELETE FROM definitions WHERE source = ?", (source,))
    conn.commit()


def insert_definitions(conn: sqlite3.Connection, definitions: list[tuple]) -> None:
    """Batch insert definitions.

    Each tuple: (source, symbol, qualified_name, file_path, line, kind, containing_type)
    """
    conn.executemany(
        "INSERT INTO definitions (source, symbol, qualified_name, file_path, line, kind, containing_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        definitions,
    )
    conn.commit()


def lookup_symbol(
    db_path: Path,
    symbol: str,
    source: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    """Look up a symbol in the definitions database.

    Cascade: exact match -> case-insensitive -> qualified_name LIKE %symbol%.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _upgrade_db(conn)

    def _add_filters(query: str, params: list) -> tuple[str, list]:
        if source:
            query += " AND source = ?"
            params.append(source)
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        return query, params

    # 1. Exact match
    query = "SELECT * FROM definitions WHERE symbol = ?"
    params: list = [symbol]
    query, params = _add_filters(query, params)
    rows = conn.execute(query, params).fetchall()

    # 2. Case-insensitive fallback
    if not rows:
        query = "SELECT * FROM definitions WHERE symbol = ? COLLATE NOCASE"
        params = [symbol]
        query, params = _add_filters(query, params)
        rows = conn.execute(query, params).fetchall()

    # 3. Qualified name partial match
    if not rows:
        query = "SELECT * FROM definitions WHERE qualified_name LIKE ? LIMIT 20"
        params = [f"%{symbol}%"]
        query, params = _add_filters(query, params)
        rows = conn.execute(query, params).fetchall()

    conn.close()
    return [dict(row) for row in rows]
