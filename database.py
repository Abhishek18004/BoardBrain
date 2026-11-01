import sqlite3
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "boardbrain.db"

DEFAULT_GAMES = [
    ("catan", "Catan"),
    ("uno", "UNO"),
    ("monopoly", "Monopoly")
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():

    with get_connection() as conn:

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rulebooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                page_count INTEGER DEFAULT 0,
                index_path TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(game_id)
                    REFERENCES games(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(game_id)
                    REFERENCES games(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS pending_uploads (
                token TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rulebooks_game
            ON rulebooks(game_id);

            CREATE INDEX IF NOT EXISTS idx_notes_game
            ON notes(game_id);
        """)

        for game_id, name in DEFAULT_GAMES:

            conn.execute(
                """
                INSERT OR IGNORE INTO games
                (id, name, is_default, created_at)
                VALUES (?, ?, 1, ?)
                """,
                (game_id, name, now_iso())
            )


# ---------------------------------------------------------
# GAMES
# ---------------------------------------------------------

def get_all_games():

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT
                g.*,
                r.status AS rulebook_status,
                r.original_filename,
                r.page_count
            FROM games g
            LEFT JOIN rulebooks r
                ON r.id = (
                    SELECT MAX(r2.id)
                    FROM rulebooks r2
                    WHERE r2.game_id = g.id
                )
            ORDER BY
                g.is_default DESC,
                g.name COLLATE NOCASE ASC
        """).fetchall()

        return [dict(row) for row in rows]


def get_game(game_id):

    with get_connection() as conn:

        row = conn.execute(
            "SELECT * FROM games WHERE id = ?",
            (game_id,)
        ).fetchone()

        return dict(row) if row else None


def create_game(game_id, name):

    name = name.strip()

    if not game_id or not name:
        raise ValueError("Game ID and name are required.")

    with get_connection() as conn:

        conn.execute(
            """
            INSERT INTO games
            (id, name, is_default, created_at)
            VALUES (?, ?, 0, ?)
            """,
            (game_id, name, now_iso())
        )

    return get_game(game_id)


# ---------------------------------------------------------
# RULEBOOKS
# ---------------------------------------------------------

def save_rulebook(
    game_id,
    filename,
    original_filename,
    page_count=0,
    index_path=None,
    status="processing"
):

    with get_connection() as conn:

        cursor = conn.execute(
            """
            INSERT INTO rulebooks
            (
                game_id,
                filename,
                original_filename,
                status,
                page_count,
                index_path,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                filename,
                original_filename,
                status,
                page_count,
                index_path,
                now_iso()
            )
        )

        return cursor.lastrowid


def update_rulebook_status(
    rulebook_id,
    status,
    page_count=None,
    index_path=None
):

    with get_connection() as conn:

        conn.execute(
            """
            UPDATE rulebooks
            SET
                status = ?,
                page_count = COALESCE(?, page_count),
                index_path = COALESCE(?, index_path)
            WHERE id = ?
            """,
            (
                status,
                page_count,
                index_path,
                rulebook_id
            )
        )


def get_latest_rulebook(game_id):

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM rulebooks
            WHERE game_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (game_id,)
        ).fetchone()

        return dict(row) if row else None


def get_active_rulebook(game_id):

    # Only a successfully indexed rulebook can be active.
    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM rulebooks
            WHERE game_id = ?
              AND status = 'ready'
            ORDER BY id DESC
            LIMIT 1
            """,
            (game_id,)
        ).fetchone()

        return dict(row) if row else None


# ---------------------------------------------------------
# TEMPORARY UPLOADS
# ---------------------------------------------------------

def save_pending_upload(
    token,
    filename,
    original_filename
):

    with get_connection() as conn:

        conn.execute(
            """
            INSERT INTO pending_uploads
            (token, filename, original_filename, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                token,
                filename,
                original_filename,
                now_iso()
            )
        )


def get_pending_upload(token):

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM pending_uploads
            WHERE token = ?
            """,
            (token,)
        ).fetchone()

        return dict(row) if row else None


def delete_pending_upload(token):

    with get_connection() as conn:

        conn.execute(
            """
            DELETE FROM pending_uploads
            WHERE token = ?
            """,
            (token,)
        )


# ---------------------------------------------------------
# NOTES
# ---------------------------------------------------------

def save_note(game_id, content):

    content = content.strip()

    if not content:
        raise ValueError("Note cannot be empty.")

    with get_connection() as conn:

        cursor = conn.execute(
            """
            INSERT INTO notes
            (game_id, content, created_at)
            VALUES (?, ?, ?)
            """,
            (game_id, content, now_iso())
        )

        return cursor.lastrowid


def get_notes(game_id):

    with get_connection() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM notes
            WHERE game_id = ?
            ORDER BY id DESC
            """,
            (game_id,)
        ).fetchall()

        return [dict(row) for row in rows]


def delete_note(note_id, game_id):

    with get_connection() as conn:

        cursor = conn.execute(
            """
            DELETE FROM notes
            WHERE id = ? AND game_id = ?
            """,
            (note_id, game_id)
        )

        return cursor.rowcount > 0