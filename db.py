"""
Optimized database module for high-concurrency GRP-CHAT.

Key optimizations for leaderboard performance:
- Persistent write connection (avoids open/close overhead per request)
- Thread-local read connections (no contention between readers)
- WAL mode with larger cache and faster synchronous settings
- Reduced lock contention: readers never block writers in WAL mode
"""
import os
import sqlite3
import threading

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_chat.db")
DB_PATH = os.environ.get("CHAT_DB_PATH", DEFAULT_DB_PATH)

# Global write lock — only one writer at a time (SQLite WAL allows concurrent reads)
_write_lock = threading.Lock()

# Thread-local storage for read connections (one per thread, persistent)
_local = threading.local()


def _get_read_conn():
    """Get or create a thread-local read connection."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        conn = sqlite3.connect(
            DB_PATH,
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA cache_size=-16384;")  # 16MB cache per connection
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
        _local.conn = conn
    return _local.conn


_local_write = threading.local()


def get_conn():
    """Get or reuse a thread-local write connection."""
    if not hasattr(_local_write, 'conn') or _local_write.conn is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        conn = sqlite3.connect(
            DB_PATH,
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=20000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA cache_size=-16384;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA mmap_size=268435456;")
        _local_write.conn = conn
    return _local_write.conn


def init_db():
    conn = get_conn()
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id      TEXT UNIQUE,
                username    TEXT NOT NULL,
                ciphertext  TEXT NOT NULL,
                signature   TEXT NOT NULL,
                pubkey_jwk  TEXT NOT NULL,
                timestamp   INTEGER NOT NULL,
                prev_hash   TEXT NOT NULL,
                record_hash TEXT NOT NULL
            )
        """)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "msg_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN msg_id TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_msg_id ON messages(msg_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username   TEXT PRIMARY KEY,
                pubkey_jwk TEXT NOT NULL
            )
        """)
    finally:
        conn.close()


def get_last_hash() -> str:
    """Tail of the hash chain — uses thread-local read conn."""
    conn = _get_read_conn()
    row = conn.execute(
        "SELECT record_hash FROM messages ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["record_hash"] if row else "0" * 64


def save_message_atomic(msg_id, username, ciphertext, signature, pubkey_jwk, timestamp, compute_hash_fn):
    """
    Atomically checks for duplicate msg_id, links to the current hash chain tail
    under an exclusive BEGIN IMMEDIATE transaction, and inserts the message.
    Guarantees no branching in the hash chain and zero duplicates.
    Uses a fresh write connection per call to avoid gevent issues.
    """
    with _write_lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()

            # 1. Fast idempotency check
            cur.execute("SELECT id, msg_id, username, timestamp, record_hash FROM messages WHERE msg_id = ?", (msg_id,))
            existing = cur.fetchone()
            if existing:
                conn.execute("COMMIT")
                return False, dict(existing)

            # 2. Get true serialized tail of the hash chain
            cur.execute("SELECT record_hash FROM messages ORDER BY id DESC LIMIT 1")
            last_row = cur.fetchone()
            prev_hash = last_row["record_hash"] if last_row else "0" * 64

            record_hash = compute_hash_fn(prev_hash, username, ciphertext, signature, timestamp)

            cur.execute(
                """INSERT INTO messages
                   (msg_id, username, ciphertext, signature, pubkey_jwk, timestamp, prev_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(msg_id) DO NOTHING""",
                (msg_id, username, ciphertext, signature, pubkey_jwk, timestamp, prev_hash, record_hash)
            )
            inserted = cur.rowcount > 0
            conn.execute("COMMIT")
            return inserted, {
                "msg_id": msg_id,
                "username": username,
                "timestamp": timestamp,
                "prev_hash": prev_hash,
                "record_hash": record_hash,
            }
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            _local_write.conn = None
            raise


def save_message(username, ciphertext, signature, pubkey_jwk, timestamp, prev_hash, record_hash, msg_id=None):
    if not msg_id:
        import uuid
        msg_id = str(uuid.uuid4())
    with _write_lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO messages
                   (msg_id, username, ciphertext, signature, pubkey_jwk, timestamp, prev_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(msg_id) DO NOTHING""",
                (msg_id, username, ciphertext, signature, pubkey_jwk, timestamp, prev_hash, record_hash)
            )
            inserted = cur.rowcount > 0
            conn.execute("COMMIT")
            return inserted
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            _local_write.conn = None
            raise


def load_history(limit=1000):
    """Read-only history fetch — uses thread-local read connection for speed."""
    conn = _get_read_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        # If thread-local conn is stale, reset and retry once
        _local.conn = None
        conn = _get_read_conn()
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_message_by_id(msg_id):
    conn = _get_read_conn()
    try:
        row = conn.execute(
            "SELECT * FROM messages WHERE msg_id = ?", (msg_id,)
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        _local.conn = None
        conn = _get_read_conn()
        row = conn.execute(
            "SELECT * FROM messages WHERE msg_id = ?", (msg_id,)
        ).fetchone()
        return dict(row) if row else None


def upsert_user_pubkey(username, pubkey_jwk_str):
    with _write_lock:
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO users (username, pubkey_jwk) VALUES (?, ?) "
                "ON CONFLICT(username) DO UPDATE SET pubkey_jwk = excluded.pubkey_jwk",
                (username, pubkey_jwk_str)
            )
        except Exception:
            _local_write.conn = None
            raise


def get_user_pubkey(username):
    conn = _get_read_conn()
    try:
        row = conn.execute(
            "SELECT pubkey_jwk FROM users WHERE username = ?", (username,)
        ).fetchone()
        return row["pubkey_jwk"] if row else None
    except Exception:
        _local.conn = None
        conn = _get_read_conn()
        row = conn.execute(
            "SELECT pubkey_jwk FROM users WHERE username = ?", (username,)
        ).fetchone()
        return row["pubkey_jwk"] if row else None