"""База данных SQLite — хранит подписчиков, сигналы, лиды, логи."""
import sqlite3, os, json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/blomster.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт все таблицы при первом запуске."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS subscribers (
        id            TEXT PRIMARY KEY,
        email         TEXT NOT NULL,
        name          TEXT DEFAULT '',
        plan          TEXT DEFAULT '',
        agents        TEXT DEFAULT '',
        content_topics TEXT DEFAULT '',
        active        INTEGER DEFAULT 1,
        stripe_sub_id TEXT DEFAULT '',
        created_at    TEXT DEFAULT (datetime('now')),
        paid_until    TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS agent_logs (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        agent  TEXT NOT NULL,
        action TEXT NOT NULL,
        detail TEXT DEFAULT '',
        ts     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS agent_results (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        agent       TEXT NOT NULL,
        result_type TEXT NOT NULL,
        content     TEXT DEFAULT '',
        client_id   TEXT DEFAULT '',
        delivered   INTEGER DEFAULT 0,
        ts          TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS leads (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        url       TEXT NOT NULL,
        email     TEXT DEFAULT '',
        description TEXT DEFAULT '',
        score     INTEGER DEFAULT 0,
        fit       TEXT DEFAULT '',
        pitch     TEXT DEFAULT '',
        status    TEXT DEFAULT 'new',
        ts        TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS signals (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        coin    TEXT NOT NULL,
        action  TEXT NOT NULL,
        price   REAL DEFAULT 0,
        content TEXT DEFAULT '',
        ts      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS payments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        stripe_id     TEXT UNIQUE,
        subscriber_id TEXT,
        amount_nok    REAL DEFAULT 0,
        plan          TEXT DEFAULT '',
        status        TEXT DEFAULT 'pending',
        ts            TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()
    print("✅ Database initialized:", DB_PATH)


# ── Subscribers ─────────────────────────────────────────────
def add_subscriber(email: str, name: str, plan: str, agents: str = "") -> str:
    import uuid
    sub_id = str(uuid.uuid4())[:8]
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO subscribers (id,email,name,plan,agents) VALUES (?,?,?,?,?)",
        (sub_id, email, name, plan, agents)
    )
    conn.commit()
    conn.close()
    return sub_id


def get_subscribers(plan: str = None, active: bool = True) -> list:
    conn = get_conn()
    if plan:
        rows = conn.execute(
            "SELECT * FROM subscribers WHERE plan=? AND active=?", (plan, int(active))
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM subscribers WHERE active=?", (int(active),)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Leads ────────────────────────────────────────────────────
def save_lead(lead: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO leads (url,email,description,score,fit,pitch,status) VALUES (?,?,?,?,?,?,?)",
        (lead.get("url"), lead.get("email",""), lead.get("description",""),
         lead.get("score",0), lead.get("fit",""), lead.get("pitch",""),
         lead.get("status","new"))
    )
    lead_id = cur.lastrowid
    conn.commit()
    conn.close()
    return lead_id


def get_leads(url: str = None) -> list:
    conn = get_conn()
    if url:
        rows = conn.execute("SELECT * FROM leads WHERE url=?", (url,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads ORDER BY ts DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_lead_contacted(lead_id: int):
    conn = get_conn()
    conn.execute("UPDATE leads SET status='contacted' WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()


# ── Stats for dashboard ──────────────────────────────────────
def get_stats() -> dict:
    conn = get_conn()
    total_subs   = conn.execute("SELECT COUNT(*) FROM subscribers WHERE active=1").fetchone()[0]
    total_revenue = conn.execute("SELECT SUM(amount_nok) FROM payments WHERE status='paid'").fetchone()[0] or 0
    total_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    total_leads   = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    recent_logs   = conn.execute(
        "SELECT * FROM agent_logs ORDER BY ts DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return {
        "subscribers":   total_subs,
        "revenue_nok":   total_revenue,
        "signals_sent":  total_signals,
        "leads_found":   total_leads,
        "recent_logs":   [dict(r) for r in recent_logs],
    }
