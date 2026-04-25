"""
AIIterate Database Layer — SQLAlchemy Core
Supports: sqlite / postgresql / mysql / oracle
Config file: config/db.json
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text, Engine

# ── Config paths ──────────────────────────────────────────────────────────────

BASE_DIR            = Path(__file__).parent
CONFIG_DIR          = BASE_DIR / "config"
KNOWLEDGE_TREE_PATH = CONFIG_DIR / "knowledge_tree.json"
DB_CONFIG_PATH      = CONFIG_DIR / "db.json"
PROFILE_ID          = "default"

# ── DB config load/save ───────────────────────────────────────────────────────

_DEFAULT_DB_CFG = {
    "type":        "postgresql",
    "host":        "127.0.0.1",
    "port":        5432,
    "dbname":      "aiterate",
    "user":        "geekinney",
    "password":    "",
    "sqlite_path": "~/.aiterate/data.db",
}

def load_db_config() -> dict:
    if DB_CONFIG_PATH.exists():
        try:
            raw = json.loads(DB_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = {**_DEFAULT_DB_CFG, **raw}
        except Exception:
            cfg = dict(_DEFAULT_DB_CFG)
    else:
        cfg = dict(_DEFAULT_DB_CFG)
    # 拒绝未实现的数据库类型
    db_type = cfg.get("type", "")
    if db_type in ("mysql", "oracle"):
        raise RuntimeError(
            f"数据库类型 '{db_type}' 尚未实现（SQL/方言未适配）。"
            f"请使用 sqlite 或 postgresql。"
        )
    return cfg

def save_db_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    merged = {**load_db_config(), **cfg}
    DB_CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def test_db_config(updates: dict) -> dict:
    """Test a candidate DB config without saving. Returns {"ok": True} or {"ok": False, "error": str}."""
    try:
        candidate = {**load_db_config(), **updates}
        url = _build_url(candidate)
        test_engine = create_engine(url)
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        test_engine.dispose()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Engine factory ─────────────────────────────────────────────────────────────

def _build_url(cfg: dict) -> str:
    t = cfg.get("type", "postgresql").lower()
    if t == "sqlite":
        path = Path(cfg.get("sqlite_path", "~/.aiterate/data.db")).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    # 需要密码的方言
    user     = cfg.get("user",     "")
    password = cfg.get("password", "")
    host     = cfg.get("host",     "127.0.0.1")
    port     = cfg.get("port",     5432)
    dbname   = cfg.get("dbname",   "aiterate")
    from urllib.parse import quote_plus
    pw = quote_plus(password) if password else ""
    auth = f"{user}:{pw}@" if user else ""
    if t == "postgresql":
        dialect = "postgresql+psycopg2"
    elif t == "mysql":
        dialect = "mysql+pymysql"
    elif t == "oracle":
        dialect = "oracle+cx_oracle"
        svc = cfg.get("service_name", dbname)
        return f"{dialect}://{auth}{host}:{port}/?service_name={svc}"
    else:
        raise ValueError(f"Unsupported db type: {t}")
    return f"{dialect}://{auth}{host}:{port}/{dbname}"

# 全局 engine，启动时由 init_engine() 初始化
_engine: Engine | None = None

def init_engine(cfg: dict | None = None):
    global _engine
    if cfg is None:
        cfg = load_db_config()
    url = _build_url(cfg)
    kwargs: dict = {"echo": False}
    if cfg.get("type", "postgresql") == "sqlite":
        # SQLite 需要同一线程连接共享
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)

def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    return _engine

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_sqlite() -> bool:
    cfg = load_db_config()
    return cfg.get("type", "postgresql").lower() == "sqlite"

def _now_expr():
    """当前时间表达式（SQLite 兼容）"""
    if _is_sqlite():
        return text("datetime('now')")
    return text("NOW()")

def _serial_col(name: str) -> str:
    """自增主键语法"""
    if _is_sqlite():
        return f"{name} INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"{name} SERIAL PRIMARY KEY"

def _timestamptz() -> str:
    if _is_sqlite():
        return "TEXT"
    return "TIMESTAMPTZ"

def _jsonb() -> str:
    if _is_sqlite():
        return "TEXT"
    return "JSONB"

def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensure_column(conn, table: str, column: str, col_type: str, default: str = None):
    """Add column if it doesn't exist (idempotent). Works for SQLite and PostgreSQL."""
    cfg = load_db_config()
    db_type = cfg.get("type", "")

    if db_type == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}
        if column not in existing:
            ddl = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            conn.execute(text(ddl))
    else:
        # PostgreSQL
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": column}).fetchall()
        if not rows:
            ddl = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            conn.execute(text(ddl))

from contextlib import contextmanager


def _exec(sql: str, params=None):
    """Execute non-returning SQL in a transaction."""
    with get_engine().begin() as conn:
        conn.execute(text(sql), params or {})


@contextmanager
def _tx():
    """Provide a connection in a transaction. Commits on success, rolls back on error.
    
    Usage:
        with _tx() as conn:
            conn.execute(text(...))
            conn.execute(text(...))
    """
    with get_engine().begin() as conn:
        yield conn

def _fetch_one(sql: str, params=None) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().fetchone()
        return dict(row) if row else None

def _fetch_all(sql: str, params=None) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().fetchall()
        return [dict(r) for r in rows]

def _insert_returning_id(sql: str, params=None) -> int:
    """INSERT ... RETURNING id；SQLite 用 lastrowid"""
    with get_engine().begin() as conn:
        if _is_sqlite():
            # SQLite 不支持 RETURNING，用 lastrowid
            sql_no_returning = sql.rstrip().rstrip(";").rsplit("RETURNING", 1)[0].rstrip()
            result = conn.execute(text(sql_no_returning), params or {})
            return result.lastrowid
        else:
            row = conn.execute(text(sql), params or {}).mappings().fetchone()
            return row["id"]

def _jload(v):
    """从 DB 读出可能是 str 也可能是 dict/list 的 JSON 字段"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v

# ── Schema ─────────────────────────────────────────────────────────────────────

def init_db():
    cfg = load_db_config()
    init_engine(cfg)

    ts  = _timestamptz()
    jb  = _jsonb()
    sqlite = _is_sqlite()

    with get_engine().begin() as conn:
        # sessions
        if sqlite:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT        NOT NULL,
                content         TEXT,
                type            TEXT        NOT NULL DEFAULT 'question',
                status          TEXT        NOT NULL DEFAULT 'preparing',
                material        TEXT,
                score           INTEGER,
                review_report   TEXT,
                knowledge_node_id TEXT,
                web_search      INTEGER     NOT NULL DEFAULT 0,
                error_msg       TEXT,
                created_at      TEXT        NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT        NOT NULL DEFAULT (datetime('now'))
            )"""))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                id         SERIAL PRIMARY KEY,
                title      TEXT        NOT NULL,
                content    TEXT,
                type       TEXT        NOT NULL DEFAULT 'question',
                status     TEXT        NOT NULL DEFAULT 'preparing',
                material   TEXT,
                score      SMALLINT,
                review_report {jb},
                knowledge_node_id TEXT,
                web_search      SMALLINT    NOT NULL DEFAULT 0,
                error_msg  TEXT,
                created_at {ts} NOT NULL DEFAULT NOW(),
                updated_at {ts} NOT NULL DEFAULT NOW()
            )"""))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC)"
            ))

        # ── 迁移：为已有表添加缺失列（SQLite + PostgreSQL）──
        _ensure_column(conn, "sessions", "review_report", "TEXT")
        _ensure_column(conn, "sessions", "knowledge_node_id", "TEXT")
        _ensure_column(conn, "sessions", "web_search", "SMALLINT", "0")
        _ensure_column(conn, "rounds", "eval_json", "TEXT")

        # rounds
        if sqlite:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS rounds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                seq           INTEGER NOT NULL,
                type          TEXT    NOT NULL,
                input         TEXT,
                output        TEXT,
                eval_json     TEXT,
                score_comment TEXT,
                group_id      INTEGER,
                score         INTEGER,
                status        TEXT    NOT NULL DEFAULT 'pending',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (session_id, seq)
            )"""))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS rounds (
                id            SERIAL PRIMARY KEY,
                session_id    INTEGER  NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                seq           SMALLINT NOT NULL,
                type          TEXT     NOT NULL,
                input         TEXT,
                output        TEXT,
                eval_json     {jb},
                score_comment TEXT,
                group_id      INTEGER,
                score         SMALLINT,
                status        TEXT     NOT NULL DEFAULT 'pending',
                created_at    {ts}     NOT NULL DEFAULT NOW(),
                UNIQUE (session_id, seq)
            )"""))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id)"
            ))

        # profile
        if sqlite:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS profile (
                id         TEXT NOT NULL PRIMARY KEY DEFAULT 'default',
                theme      TEXT NOT NULL DEFAULT 'night',
                settings   TEXT NOT NULL DEFAULT '{{}}',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS profile (
                id         TEXT        PRIMARY KEY DEFAULT 'default',
                theme      TEXT        NOT NULL DEFAULT 'night',
                settings   {jb}        NOT NULL DEFAULT '{{}}',
                updated_at {ts}        NOT NULL DEFAULT NOW()
            )"""))

        # 默认 profile（幂等）
        if sqlite:
            conn.execute(text(
                "INSERT OR IGNORE INTO profile (id) VALUES ('default')"
            ))
        else:
            conn.execute(text(
                "INSERT INTO profile (id) VALUES ('default') ON CONFLICT (id) DO NOTHING"
            ))

        # review_schedule — 复习排期 (Phase 4.2: +user_content, ai_feedback, review_score)
        if sqlite:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS review_schedule (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                review_date     TEXT    NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'pending',
                user_content    TEXT,
                ai_feedback     TEXT,
                review_score    INTEGER,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                completed_at    TEXT
            )"""))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS review_schedule (
                id         SERIAL PRIMARY KEY,
                session_id INTEGER  NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                review_date DATE    NOT NULL,
                status     TEXT     NOT NULL DEFAULT 'pending',
                user_content TEXT,
                ai_feedback  TEXT,
                review_score SMALLINT,
                created_at {ts}     NOT NULL DEFAULT NOW(),
                updated_at {ts}     NOT NULL DEFAULT NOW(),
                completed_at {ts}
            )"""))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_review_schedule_date ON review_schedule(review_date)"
            ))
            # 迁移：为旧表添加列
            for col, col_type in [("completed_at", ts), ("user_content", "TEXT"),
                                   ("ai_feedback", "TEXT"), ("review_score", "SMALLINT")]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE review_schedule ADD COLUMN IF NOT EXISTS {col} {col_type}"
                    ))
                except Exception:
                    pass  # SQLite 不支持 IF NOT EXISTS in ALTER TABLE

        # jobs — Phase 4: DB-backed async job queue
        if sqlite:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type        TEXT    NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'pending',
                payload         TEXT,
                result          TEXT,
                error_msg       TEXT,
                retries         INTEGER NOT NULL DEFAULT 0,
                max_retries     INTEGER NOT NULL DEFAULT 3,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                started_at      TEXT,
                claimed_at      TEXT,
                completed_at    TEXT
            )"""))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS jobs (
                id         SERIAL PRIMARY KEY,
                job_type   TEXT     NOT NULL,
                status     TEXT     NOT NULL DEFAULT 'pending',
                payload    {jb},
                result     {jb},
                error_msg  TEXT,
                retries    SMALLINT NOT NULL DEFAULT 0,
                max_retries SMALLINT NOT NULL DEFAULT 3,
                created_at {ts}     NOT NULL DEFAULT NOW(),
                started_at {ts},
                claimed_at {ts},
                completed_at {ts}
            )"""))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at)"
            ))

    # 迁移旧格式 settings（幂等）
    _migrate_settings()

    print(f"[DB] aiterate ready — {cfg.get('type','postgresql')} — sessions / rounds / profile / review_schedule / jobs")


_LLM_ROLES = ["title", "answer", "evaluate", "review", "deepen"]

def _migrate_settings():
    p = _fetch_one("SELECT settings FROM profile WHERE id = :id", {"id": PROFILE_ID})
    if not p:
        return
    raw = p["settings"]
    s = _jload(raw) if raw else {}
    if not isinstance(s, dict):
        s = {}
    if "llm" in s:
        return  # 已是新格式

    llm = {
        "provider": s.get("llm_default_provider", ""),
        "base_url":  s.get("llm_default_base_url", ""),
        "api_key":   s.get("llm_default_api_key", ""),
        "model":     s.get("llm_default_model", ""),
        "roles": {},
    }
    for role in _LLM_ROLES:
        rc = {
            "provider": s.get(f"llm_{role}_provider", ""),
            "base_url":  s.get(f"llm_{role}_base_url", ""),
            "api_key":   s.get(f"llm_{role}_api_key", ""),
            "model":     s.get(f"llm_{role}_model", ""),
        }
        if any(rc.values()):
            llm["roles"][role] = rc

    new_s = {"llm": llm, "tavily_api_key": s.get("tavily_api_key", "")}
    _exec(
        "UPDATE profile SET settings = :s, updated_at = :t WHERE id = :id",
        {"s": json.dumps(new_s), "t": _now_str(), "id": PROFILE_ID},
    )
    print("[DB] settings migrated to nested format")


# ── Profile ────────────────────────────────────────────────────────────────────

def get_profile() -> dict:
    r = _fetch_one("SELECT * FROM profile WHERE id = :id", {"id": PROFILE_ID})
    if not r:
        return {"id": PROFILE_ID, "theme": "night", "settings": {}}
    r["settings"] = _jload(r.get("settings") or {})
    if not isinstance(r["settings"], dict):
        r["settings"] = {}
    return r

def get_settings() -> dict:
    return get_profile().get("settings") or {}


def get_or_create_admin_token() -> str:
    """Return admin token. Auto-generate UUID on first call and persist."""
    import uuid
    settings = get_settings()
    token = settings.get("admin_token", "")
    if not token:
        token = uuid.uuid4().hex
        upsert_profile(**{"settings__admin_token": token})
    return token


def check_admin_token(token: str | None) -> bool:
    """Verify admin token using constant-time comparison."""
    if not token:
        return False
    expected = get_settings().get("admin_token", "")
    if not expected:
        return False
    import secrets
    return secrets.compare_digest(token, expected)


def upsert_profile(**kwargs) -> dict:
    cur      = get_profile()
    settings = dict(cur.get("settings") or {})
    direct   = {}

    for k, v in kwargs.items():
        if k.startswith("settings__"):
            key = k[10:]
            if key == "llm" and isinstance(v, dict):
                existing = settings.get("llm", {})
                existing.update(v)
                settings["llm"] = existing
            else:
                settings[key] = v
        else:
            direct[k] = v

    theme = direct.get("theme", cur["theme"])
    if "settings" in direct:
        settings.update(direct["settings"])

    s_json = json.dumps(settings)
    if _is_sqlite():
        _exec("""
        INSERT INTO profile (id, theme, settings, updated_at)
        VALUES (:id, :theme, :settings, :ts)
        ON CONFLICT(id) DO UPDATE SET
            theme=excluded.theme, settings=excluded.settings, updated_at=excluded.updated_at
        """, {"id": PROFILE_ID, "theme": theme, "settings": s_json, "ts": _now_str()})
    else:
        _exec("""
        INSERT INTO profile (id, theme, settings, updated_at)
        VALUES (:id, :theme, CAST(:settings AS jsonb), NOW())
        ON CONFLICT (id) DO UPDATE
            SET theme=EXCLUDED.theme, settings=CAST(EXCLUDED.settings AS jsonb), updated_at=NOW()
        """, {"id": PROFILE_ID, "theme": theme, "settings": s_json})

    return get_profile()


# ── Sessions ───────────────────────────────────────────────────────────────────

def create_session(title: str, content: str = "", type: str = "question", web_search: bool = False) -> int:
    if _is_sqlite():
        return _insert_returning_id("""
        INSERT INTO sessions (title, content, type, status, web_search)
        VALUES (:title, :content, :type, 'preparing', :web_search) RETURNING id
        """, {"title": title, "content": content, "type": type, "web_search": int(web_search)})
    else:
        return _insert_returning_id("""
        INSERT INTO sessions (title, content, type, status, web_search)
        VALUES (:title, :content, :type, 'preparing', :web_search) RETURNING id
        """, {"title": title, "content": content, "type": type, "web_search": int(web_search)})

def get_session(session_id: int) -> dict | None:
    return _fetch_one("SELECT * FROM sessions WHERE id = :id", {"id": session_id})

def get_recent_sessions(limit: int = 20) -> list[dict]:
    return _fetch_all(
        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT :lim",
        {"lim": limit}
    )

def update_session(session_id: int, **kwargs):
    parts = []
    params = {}
    for k, v in kwargs.items():
        parts.append(f"{k} = :{k}")
        params[k] = v
    # updated_at
    if _is_sqlite():
        parts.append("updated_at = :__now")
        params["__now"] = _now_str()
    else:
        parts.append("updated_at = NOW()")
    params["__id"] = session_id
    _exec(f"UPDATE sessions SET {', '.join(parts)} WHERE id = :__id", params)

def get_stats() -> dict:
    total     = (_fetch_one("SELECT COUNT(*) AS n FROM sessions") or {}).get("n", 0)
    completed = (_fetch_one("SELECT COUNT(*) AS n FROM sessions WHERE status = 'completed'") or {}).get("n", 0)
    if _is_sqlite():
        avg_row = _fetch_one("SELECT ROUND(AVG(score), 1) AS v FROM sessions WHERE score IS NOT NULL")
    else:
        avg_row = _fetch_one("SELECT ROUND(AVG(score)::numeric, 1) AS v FROM sessions WHERE score IS NOT NULL")
    avg_score = (avg_row or {}).get("v")

    if _is_sqlite():
        recent = _fetch_all("""
        SELECT DATE(created_at) AS d, COUNT(*) AS n
        FROM sessions WHERE created_at >= datetime('now', '-7 days')
        GROUP BY d ORDER BY d
        """)
    else:
        recent = _fetch_all("""
        SELECT DATE(created_at) AS d, COUNT(*) AS n
        FROM sessions WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY d ORDER BY d
        """)

    return {
        "total_sessions":     total,
        "completed_sessions": completed,
        "avg_score":          float(avg_score) if avg_score else 0.0,
        "recent_7days":       recent,
    }


# ── Rounds ─────────────────────────────────────────────────────────────────────

def next_seq(session_id: int) -> int:
    """Get next seq number for a session. Use create_round_with_seq() for atomicity."""
    row = _fetch_one(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM rounds WHERE session_id = :sid",
        {"sid": session_id}
    )
    return (row["m"] if row else 0) + 1


def create_round(session_id: int, seq: int, type: str,
                 input: str | None = None,
                 output: str | None = None,
                 score: int | None = None,
                 status: str = "pending") -> int:
    return _insert_returning_id("""
    INSERT INTO rounds (session_id, seq, type, input, output, score, status)
    VALUES (:sid, :seq, :type, :input, :output, :score, :status) RETURNING id
    """, {"sid": session_id, "seq": seq, "type": type,
          "input": input, "output": output, "score": score, "status": status})


def create_round_with_seq(session_id: int, type: str,
                          input: str | None = None,
                          output: str | None = None,
                          score: int | None = None,
                          status: str = "pending",
                          eval_json: dict | None = None) -> int:
    """Atomically compute next seq and create a round. Prevents seq conflicts."""
    eval_str = json.dumps(eval_json, ensure_ascii=False) if eval_json else None
    with _tx() as conn:
        row = conn.execute(
            text("SELECT COALESCE(MAX(seq), 0) AS m FROM rounds WHERE session_id = :sid"),
            {"sid": session_id}
        ).fetchone()
        next_s = (row._mapping["m"] if row else 0) + 1
        result = conn.execute(
            text("""
                INSERT INTO rounds (session_id, seq, type, input, output, score, status, eval_json)
                VALUES (:sid, :seq, :type, :input, :output, :score, :status, :ejson) RETURNING id
            """),
            {"sid": session_id, "seq": next_s, "type": type,
             "input": input, "output": output, "score": score, "status": status,
             "ejson": eval_str}
        )
        rid = result.fetchone()._mapping["id"]
    return rid


def create_feynman_group(session_id: int, questions: list[str]) -> tuple[int, list[int]]:
    """Create a group of feynman rounds atomically.
    
    Returns (group_id, [round_ids]). All-or-nothing: either all rounds are
    created with correct group_id and seq, or nothing is.
    """
    with _tx() as conn:
        row = conn.execute(
            text("SELECT COALESCE(MAX(seq), 0) AS m FROM rounds WHERE session_id = :sid"),
            {"sid": session_id}
        ).fetchone()
        seq_start = (row._mapping["m"] if row else 0) + 1

        round_ids = []
        first_id = None
        for i, q in enumerate(questions):
            result = conn.execute(
                text("""
                    INSERT INTO rounds (session_id, seq, type, input, output, score, status, group_id)
                    VALUES (:sid, :seq, 'feynman', :input, NULL, NULL, 'pending', 0) RETURNING id
                """),
                {"sid": session_id, "seq": seq_start + i, "input": q}
            )
            rid = result.fetchone()._mapping["id"]
            if first_id is None:
                first_id = rid
            round_ids.append(rid)

        # Set group_id for all rounds in this batch
        for rid in round_ids:
            conn.execute(
                text("UPDATE rounds SET group_id = :gid WHERE id = :rid"),
                {"gid": first_id, "rid": rid}
            )

        # Update session status
        conn.execute(
            text("UPDATE sessions SET status = 'feynman', updated_at = :ts WHERE id = :sid"),
            {"sid": session_id, "ts": _now_str()}
        )

    return first_id, round_ids


def complete_feynman_group(session_id: int, group_id: int,
                           answers: list[str],
                           item_scores: list[dict],
                           final_score: int,
                           new_status: str) -> dict:
    """Complete a feynman group atomically.
    
    Returns the eval result dict. Raises ValueError if group already completed
    (double-submit protection).
    """
    with _tx() as conn:
        # Check that rounds are still pending
        rows = conn.execute(
            text("SELECT id, status FROM rounds WHERE group_id = :gid AND type = 'feynman' ORDER BY seq"),
            {"gid": group_id}
        ).fetchall()
        
        if not rows:
            raise ValueError("Feynman group not found")
        
        completed_count = sum(1 for r in rows if r._mapping["status"] == "completed")
        if completed_count > 0:
            raise ValueError("This feynman group has already been submitted")
        
        if len(rows) != len(answers):
            raise ValueError(f"Expected {len(rows)} answers, got {len(answers)}")

        # Update each round
        for i, r in enumerate(rows):
            ev = item_scores[i] if i < len(item_scores) else {}
            ans = answers[i] if i < len(answers) else ""
            conn.execute(
                text("""
                    UPDATE rounds
                    SET output = :out, score = :sc, score_comment = :cm, status = 'completed'
                    WHERE id = :rid
                """),
                {"out": ans, "sc": ev.get("score"), "cm": ev.get("comment", ""), "rid": r._mapping["id"]}
            )

        # Update session
        if _is_sqlite():
            conn.execute(
                text("UPDATE sessions SET score = :sc, status = :st, updated_at = :ts WHERE id = :sid"),
                {"sc": final_score, "st": new_status, "ts": _now_str(), "sid": session_id}
            )
        else:
            conn.execute(
                text("UPDATE sessions SET score = :sc, status = :st, updated_at = NOW() WHERE id = :sid"),
                {"sc": final_score, "st": new_status, "sid": session_id}
            )

    # Build return value
    return {
        "final_score": final_score,
        "passed": new_status == "completed",
        "new_status": new_status,
        "group_id": group_id,
    }


def get_rounds(session_id: int) -> list[dict]:
    return _fetch_all(
        "SELECT * FROM rounds WHERE session_id = :sid ORDER BY seq",
        {"sid": session_id}
    )

def get_pending_feynman_group(session_id: int) -> list[dict]:
    return _fetch_all("""
    SELECT * FROM rounds
    WHERE session_id = :sid AND type = 'feynman' AND status = 'pending'
    ORDER BY seq
    """, {"sid": session_id})

def update_round(round_id: int, **kwargs):
    for key in ("input", "output"):
        if key in kwargs and isinstance(kwargs[key], list):
            kwargs[key] = json.dumps(kwargs[key], ensure_ascii=False)
    parts  = [f"{k} = :{k}" for k in kwargs]
    params = {**kwargs, "__id": round_id}
    _exec(f"UPDATE rounds SET {', '.join(parts)} WHERE id = :__id", params)


# ── Maintenance ────────────────────────────────────────────────────────────

def get_stale_preparing_sessions(timeout_minutes: int = 5) -> dict:
    """Return sessions stuck in preparing for too long."""
    if _is_sqlite():
        rows = _fetch_all(
            "SELECT id, title, content, created_at FROM sessions WHERE status = 'preparing' "
            "AND created_at < datetime('now', '-' || :tm || ' minutes') ORDER BY created_at DESC",
            {"tm": str(timeout_minutes)}
        )
    else:
        rows = _fetch_all(
            "SELECT id, title, content, created_at FROM sessions WHERE status = 'preparing' "
            "AND created_at < NOW() - (:tm || ' minutes')::INTERVAL ORDER BY created_at DESC",
            {"tm": str(timeout_minutes)}
        )
    return {"stale": rows, "count": len(rows)}


def mark_stale_preparing_as_error(timeout_minutes: int = 5):
    """Mark stale preparing sessions as error."""
    if _is_sqlite():
        _exec(
            "UPDATE sessions SET status = 'error', error_msg = :msg, updated_at = :ts "
            "WHERE status = 'preparing' AND created_at < datetime('now', '-' || :tm || ' minutes')",
            {"msg": "Background task lost (server restart)", "ts": _now_str(), "tm": str(timeout_minutes)}
        )
    else:
        _exec(
            "UPDATE sessions SET status = 'error', error_msg = :msg, updated_at = NOW() "
            "WHERE status = 'preparing' AND created_at < NOW() - (:tm || ' minutes')::INTERVAL",
            {"msg": "Background task lost (server restart)", "tm": str(timeout_minutes)}
        )


# ── Gaps ───────────────────────────────────────────────────────────────────

def get_unresolved_gaps(session_id: int) -> list[dict]:
    """Get all unresolved gaps from take rounds for a session."""
    rows = _fetch_all("""
        SELECT id, seq, eval_json, created_at FROM rounds
        WHERE session_id = :sid AND type = 'take'
        ORDER BY seq DESC
    """, {"sid": session_id})
    gaps = []
    for r in rows:
        ev = _jload(r.get("eval_json")) if r.get("eval_json") else {}
        for g in (ev.get("gaps") or []):
            gaps.append({
                "round_id": r["id"],
                "seq": r["seq"],
                "gap": g,
                "praise": ev.get("praise", ""),
                "created_at": r.get("created_at"),
            })
    return gaps


# ── Review Report ──────────────────────────────────────────────────────────

def save_review_report(session_id: int, report: dict):
    """Persist feynman review report to the session."""
    r_json = json.dumps(report, ensure_ascii=False)
    if _is_sqlite():
        _exec("""
            UPDATE sessions SET review_report = :rpt, updated_at = :ts WHERE id = :sid
        """, {"sid": session_id, "rpt": r_json, "ts": _now_str()})
    else:
        _exec("""
            UPDATE sessions SET review_report = CAST(:rpt AS jsonb), updated_at = NOW() WHERE id = :sid
        """, {"sid": session_id, "rpt": r_json})


def get_review_report(session_id: int) -> dict | None:
    """Retrieve feynman review report for a session."""
    r = _fetch_one("SELECT review_report FROM sessions WHERE id = :sid", {"sid": session_id})
    if not r or not r.get("review_report"):
        return None
    return _jload(r["review_report"])


# ── Knowledge Node ─────────────────────────────────────────────────────────

def set_knowledge_node(session_id: int, node_id: str | None):
    """Bind or unbind a knowledge node to a session."""
    params = {"sid": session_id, "nid": node_id}
    if _is_sqlite():
        _exec("""
            UPDATE sessions SET knowledge_node_id = :nid, updated_at = :ts WHERE id = :sid
        """, {**params, "ts": _now_str()})
    else:
        _exec("""
            UPDATE sessions SET knowledge_node_id = :nid, updated_at = NOW() WHERE id = :sid
        """, params)


def get_knowledge_node(session_id: int) -> str | None:
    """Get the knowledge node ID for a session."""
    r = _fetch_one("SELECT knowledge_node_id FROM sessions WHERE id = :sid", {"sid": session_id})
    return r.get("knowledge_node_id") if r else None


def find_node_by_id(tree: list, node_id: str) -> dict | None:
    """Recursively find a node in the knowledge tree by ID."""
    for node in tree:
        if node.get("id") == node_id:
            return node
        children = node.get("children", [])
        if children:
            found = find_node_by_id(children, node_id)
            if found:
                return found
    return None


def suggest_knowledge_nodes(tree: list, query: str, limit: int = 3) -> list[dict]:
    """Simple keyword-matching recommendation from knowledge tree.
    
    Matches query against node titles, keywords, and prompt_fragments.
    Returns top-N matches sorted by relevance.
    """
    query_lower = query.lower()
    scored = []

    def _walk(nodes, path=""):
        for node in nodes:
            score = 0
            title = node.get("title", "")
            keywords = node.get("keywords", [])
            fragments = node.get("prompt_fragments", [])

            # Title match (weight 3)
            if any(w in title.lower() for w in query_lower.split()):
                score += 3
            if query_lower in title.lower():
                score += 5

            # Keyword match (weight 2 each)
            for kw in keywords:
                if kw.lower() in query_lower or query_lower in kw.lower():
                    score += 2

            # Fragment match (weight 1)
            for f in fragments:
                if any(w in f.lower() for w in query_lower.split()):
                    score += 1

            if score > 0:
                node_path = f"{path}/{title}".strip("/") if path else title
                scored.append({
                    "id": node.get("id"),
                    "title": title,
                    "path": node_path,
                    "score": score,
                    "keywords": keywords,
                    "prompt_fragments": fragments,
                })

            _walk(node.get("children", []), f"{path}/{title}" if path else title)

    _walk(tree)
    scored.sort(key=lambda x: (-x["score"], x["path"]))
    return scored[:limit]


def get_knowledge_tree_progress() -> list[dict]:
    """Return progress stats for every node that has sessions."""
    if _is_sqlite():
        rows = _fetch_all("""
            SELECT 
                s.knowledge_node_id AS node_id,
                COUNT(*) AS total_sessions,
                SUM(CASE WHEN s.status = 'completed' THEN 1 ELSE 0 END) AS completed_sessions,
                SUM(CASE WHEN s.status NOT IN ('completed', 'error') THEN 1 ELSE 0 END) AS active_sessions,
                ROUND(AVG(s.score), 1) AS avg_score
            FROM sessions s
            WHERE s.knowledge_node_id IS NOT NULL
            GROUP BY s.knowledge_node_id
            ORDER BY total_sessions DESC
        """)
    else:
        rows = _fetch_all("""
            SELECT 
                s.knowledge_node_id AS node_id,
                COUNT(*) AS total_sessions,
                COUNT(*) FILTER (WHERE s.status = 'completed') AS completed_sessions,
                COUNT(*) FILTER (WHERE s.status NOT IN ('completed', 'error')) AS active_sessions,
                ROUND(AVG(s.score) FILTER (WHERE s.score IS NOT NULL)::numeric, 1) AS avg_score
            FROM sessions s
            WHERE s.knowledge_node_id IS NOT NULL
            GROUP BY s.knowledge_node_id
            ORDER BY total_sessions DESC
        """)
    result = []
    for r in rows:
        result.append({
            "node_id": r["node_id"],
            "total_sessions": int(r["total_sessions"]),
            "completed_sessions": int(r["completed_sessions"]),
            "active_sessions": int(r["active_sessions"]),
            "avg_score": float(r["avg_score"]) if r["avg_score"] else 0.0,
        })
    return result


# ── Job Queue (Phase 4) ────────────────────────────────────────────────────
# DB-backed async job queue, replaces FastAPI BackgroundTasks.
# Survives server restarts.

def create_job(job_type: str, payload: dict | None = None, max_retries: int = 3) -> int:
    """Create a pending job. Returns job id."""
    p = json.dumps(payload) if payload else None
    if _is_sqlite():
        return _insert_returning_id(
            """INSERT INTO jobs (job_type, payload, max_retries, created_at)
               VALUES (:jt, :p, :mr, datetime('now')) RETURNING id""",
            {"jt": job_type, "p": p, "mr": max_retries})
    return _insert_returning_id(
        """INSERT INTO jobs (job_type, payload, max_retries)
           VALUES (:jt, :p ::jsonb, :mr) RETURNING id""",
        {"jt": job_type, "p": p, "mr": max_retries})


def claim_pending_job() -> dict | None:
    """Claim the oldest pending job (atomic). Returns job or None."""
    job = _fetch_one(
        """UPDATE jobs SET status = 'running', started_at = NOW(), claimed_at = NOW()
           WHERE id = (
             SELECT id FROM jobs
             WHERE status = 'pending'
             ORDER BY created_at LIMIT 1
             FOR UPDATE SKIP LOCKED
           )
           RETURNING *""")
    return job


def complete_job(job_id: int, result: dict | None = None):
    """Mark a job as completed."""
    _exec(
        """UPDATE jobs SET status = 'completed', result = :r, completed_at = NOW()
           WHERE id = :id""",
        {"r": json.dumps(result) if result else None, "id": job_id})


def fail_job(job_id: int, error_msg: str, rescind: bool = False):
    """Mark a job as failed. If rescind=False and retries < max_retries, re-queue as pending."""
    job = _fetch_one("SELECT * FROM jobs WHERE id = :id", {"id": job_id})
    if not job:
        return
    current_retries = job.get("retries", 0) + 1
    max_retries = job.get("max_retries", 3)

    if not rescind and current_retries < max_retries:
        # Re-queue: increment retry count, set back to pending
        _exec(
            """UPDATE jobs SET status = 'pending', retries = :r, error_msg = :e,
               started_at = NULL, claimed_at = NULL
               WHERE id = :id""",
            {"r": current_retries, "e": error_msg, "id": job_id})
    else:
        _exec(
            """UPDATE jobs SET status = 'failed', error_msg = :e,
               retries = :r, completed_at = NOW()
               WHERE id = :id""",
            {"e": error_msg, "r": current_retries, "id": job_id})


def get_pending_job_count() -> int:
    r = _fetch_one("SELECT COUNT(*) as cnt FROM jobs WHERE status = 'pending'")
    return r["cnt"] if r else 0


def get_running_job_count() -> int:
    r = _fetch_one("SELECT COUNT(*) as cnt FROM jobs WHERE status = 'running'")
    return r["cnt"] if r else 0


def recover_stale_jobs(timeout_minutes: int = 5):
    """Reset jobs stuck in 'running' back to 'pending' (server restart recovery)."""
    warn_sessions = []
    # Recover running jobs
    jobs = _fetch_all(
        """SELECT id, job_type, payload FROM jobs
           WHERE status = 'running'
             AND started_at < NOW() - (:t || ' minutes')::interval""",
        {"t": str(timeout_minutes)})
    for j in jobs:
        _exec("UPDATE jobs SET status = 'pending', started_at = NULL, claimed_at = NULL WHERE id = :id",
              {"id": j["id"]})
        # If it's a session answer job, check if session is still stuck in preparing
        if j.get("job_type") == "generate_session_answer":
            payload = _jload(j.get("payload")) if j.get("payload") else {}
            sid = payload.get("session_id")
            if sid:
                s = _fetch_one("SELECT status FROM sessions WHERE id = :id", {"id": sid})
                if s and s.get("status") == "preparing":
                    warn_sessions.append(sid)

    return {"recovered_jobs": len(jobs), "stuck_sessions": warn_sessions}


# ── Review Schedule ────────────────────────────────────────────────────────

# 艾宾浩斯遗忘曲线间隔（天）：第 n 次复习距第 n-1 次的天数
_EBBINGHAUS_INTERVALS = [1, 2, 6, 31, 90]  # R1, R2, R3, R4, R5


def schedule_review(session_id: int, score: int | None) -> int | None:
    """创建复习排期（艾宾浩斯遗忘曲线）。

    根据已完成复习次数确定间隔：
    - 第 1 次复习：1 天后
    - 第 2 次复习：2 天后
    - 第 3 次复习：6 天后
    - 第 4 次复习：31 天后
    - 第 5 次复习：90 天后

    分数调制：score < 40 时降一档（最少 1 天）。
    已有 pending 排期时跳过，返回 None。
    """
    from datetime import date, timedelta

    # 检查是否已有 pending 排期
    existing = _fetch_one(
        "SELECT id FROM review_schedule WHERE session_id = :sid AND status = 'pending'",
        {"sid": session_id}
    )
    if existing:
        return None

    # 统计已完成复习次数 → 决定下一轮间隔
    completed = _fetch_one(
        "SELECT COUNT(*) AS n FROM review_schedule WHERE session_id = :sid AND status = 'completed'",
        {"sid": session_id}
    )
    review_round = (completed["n"] if completed else 0)  # 0 = 首次复习

    # 选择间隔
    if review_round >= len(_EBBINGHAUS_INTERVALS):
        days = _EBBINGHAUS_INTERVALS[-1]  # 超过曲线范围用最后一档
    else:
        days = _EBBINGHAUS_INTERVALS[review_round]

    # 分数调制：低分提前复习（降一档，最低 1 天）
    if score is not None and score < 40:
        if review_round > 0:
            days = max(1, _EBBINGHAUS_INTERVALS[review_round - 1])
        else:
            days = 1

    review_date = (date.today() + timedelta(days=days)).isoformat()

    if _is_sqlite():
        return _insert_returning_id("""
        INSERT INTO review_schedule (session_id, review_date) 
        VALUES (:sid, :rd) RETURNING id
        """, {"sid": session_id, "rd": review_date})
    else:
        return _insert_returning_id("""
        INSERT INTO review_schedule (session_id, review_date) 
        VALUES (:sid, :rd) RETURNING id
        """, {"sid": session_id, "rd": review_date})


def get_today_reviews(limit: int = 20) -> list[dict]:
    """获取今日到期的复习任务（含 overdue），按 review_date 升序。
    返回结果附带 review_round 字段（第几次复习，0-based）。
    """
    from datetime import date
    today = date.today().isoformat()
    return _fetch_all("""
        SELECT rs.id AS review_id, rs.review_date, rs.status AS review_status,
               s.id AS session_id, s.title, s.score, s.knowledge_node_id,
               s.status AS session_status,
               (SELECT COUNT(*) FROM review_schedule rs2 
                WHERE rs2.session_id = rs.session_id 
                  AND rs2.status = 'completed') AS review_round
        FROM review_schedule rs
        JOIN sessions s ON s.id = rs.session_id
        WHERE rs.review_date <= :today AND rs.status = 'pending'
        ORDER BY rs.review_date ASC
        LIMIT :lim
    """, {"today": today, "lim": limit})


def get_due_reviews(limit: int = 20) -> list[dict]:
    """获取直到今天为止的待复习条目（包括 overdue）。"""
    return get_today_reviews(limit)


def get_session_review_schedule(session_id: int) -> list[dict]:
    """获取某个 session 的全部复习排期记录。"""
    return _fetch_all(
        "SELECT * FROM review_schedule WHERE session_id = :sid ORDER BY review_date ASC",
        {"sid": session_id}
    )


def mark_review_complete(review_id: int, score: int | None = None):
    """标记一次复习完成，并自动排期下一轮复习（艾宾浩斯曲线）。"""
    # 获取关联的 session_id
    row = _fetch_one(
        "SELECT session_id FROM review_schedule WHERE id = :rid",
        {"rid": review_id}
    )
    if not row:
        return

    # 标记当前为完成
    ts = _now_str()
    if _is_sqlite():
        _exec("""
            UPDATE review_schedule SET status = 'completed', updated_at = :ts, completed_at = :ts2
            WHERE id = :rid
        """, {"rid": review_id, "ts": ts, "ts2": ts})
    else:
        _exec("""
            UPDATE review_schedule SET status = 'completed', updated_at = NOW(), completed_at = NOW()
            WHERE id = :rid
        """, {"rid": review_id})

    # 自动排期下一轮（不限轮数，超过曲线范围用最后一档）
    schedule_review(row["session_id"], score)


def submit_review_content(review_id: int, user_content: str, ai_feedback: str, review_score: int):
    """Phase 4.2: 提交复习内容（用户重新解释 + AI 评价），标记完成并排期下一轮。"""
    row = _fetch_one(
        "SELECT session_id FROM review_schedule WHERE id = :rid",
        {"rid": review_id}
    )
    if not row:
        return

    # 更新复习记录
    if _is_sqlite():
        ts = _now_str()
        _exec("""
            UPDATE review_schedule
            SET status = 'completed', user_content = :uc, ai_feedback = :fb,
                review_score = :sc, updated_at = :ts, completed_at = :ts2
            WHERE id = :rid
        """, {"rid": review_id, "uc": user_content, "fb": ai_feedback,
              "sc": review_score, "ts": ts, "ts2": ts})
    else:
        _exec("""
            UPDATE review_schedule
            SET status = 'completed', user_content = :uc, ai_feedback = :fb,
                review_score = :sc, updated_at = NOW(), completed_at = NOW()
            WHERE id = :rid
        """, {"rid": review_id, "uc": user_content, "fb": ai_feedback, "sc": review_score})

    # 自动排期下一轮
    schedule_review(row["session_id"], review_score)


def get_command_center_data() -> dict:
    """聚合 Command Center 需要的所有数据。"""
    # 1. 费曼未完成的 session（status=feynman 或有 pending feynman rounds）
    feynman_pending = _fetch_all("""
        SELECT DISTINCT s.id, s.title, s.score, s.knowledge_node_id, s.updated_at
        FROM sessions s
        WHERE s.status = 'feynman'
           OR EXISTS (SELECT 1 FROM rounds r WHERE r.session_id = s.id AND r.type = 'feynman' AND r.status = 'pending')
        ORDER BY s.updated_at DESC
        LIMIT 5
    """)

    # 2. 今日到期的复习
    review_due = get_today_reviews(10)

    # 3. 失败 session（真正出错的，不含 revising）
    failed_sessions = _fetch_all("""
        SELECT id, title, score, knowledge_node_id, updated_at
        FROM sessions
        WHERE status = 'error'
        ORDER BY updated_at DESC
        LIMIT 5
    """)

    # 4. 学习中的 session
    active_sessions = _fetch_all("""
        SELECT id, title, score, knowledge_node_id, status, updated_at
        FROM sessions
        WHERE status NOT IN ('completed', 'error', 'feynman')
        ORDER BY updated_at DESC
        LIMIT 5
    """)

    # 5. 推荐下一个知识节点：取有 session 但还没完成的节点
    if _is_sqlite():
        next_node_rows = _fetch_all("""
            SELECT s.knowledge_node_id, 
                   COUNT(*) AS total,
                   SUM(CASE WHEN s.status = 'completed' THEN 1 ELSE 0 END) AS done
            FROM sessions s
            WHERE s.knowledge_node_id IS NOT NULL
            GROUP BY s.knowledge_node_id
            HAVING done < total
            ORDER BY RANDOM()
            LIMIT 3
        """)
    else:
        next_node_rows = _fetch_all("""
            SELECT s.knowledge_node_id, 
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE s.status = 'completed') AS done
            FROM sessions s
            WHERE s.knowledge_node_id IS NOT NULL
            GROUP BY s.knowledge_node_id
            HAVING COUNT(*) FILTER (WHERE s.status = 'completed') < COUNT(*)
            ORDER BY RANDOM()
            LIMIT 3
        """)

    return {
        "feynman_pending": feynman_pending,
        "review_due": review_due,
        "failed_sessions": failed_sessions,
        "active_sessions": active_sessions,
        "suggested_nodes": next_node_rows,
        # 6. 未来 7 天复习计划
        "upcoming_reviews": get_upcoming_reviews(7),
        # 7. 系统健康摘要
        "health": get_system_health(),
    }


# ── System Health ──────────────────────────────────────────────────────────

def get_upcoming_reviews(days: int = 7) -> list[dict]:
    """未来 N 天的复习计划（不含已逾期的和今天的）。"""
    from datetime import date
    today = date.today().isoformat()
    if _is_sqlite():
        return _fetch_all("""
            SELECT r.id AS review_id, r.session_id, r.review_date,
                   r.status, s.title, s.score,
                   (SELECT COUNT(*) FROM review_schedule rs2
                    WHERE rs2.session_id = r.session_id
                      AND rs2.status = 'completed') AS review_round
            FROM review_schedule r
            JOIN sessions s ON s.id = r.session_id
            WHERE r.status = 'pending' AND r.review_date > :today
              AND r.review_date <= date(:today, '+' || :days || ' days')
            ORDER BY r.review_date ASC
            LIMIT 20
        """, {"today": today, "days": str(days)})
    else:
        return _fetch_all("""
            SELECT r.id AS review_id, r.session_id, r.review_date,
                   r.status, s.title, s.score,
                   (SELECT COUNT(*) FROM review_schedule rs2
                    WHERE rs2.session_id = r.session_id
                      AND rs2.status = 'completed') AS review_round
            FROM review_schedule r
            JOIN sessions s ON s.id = r.session_id
            WHERE r.status = 'pending' AND r.review_date > CAST(:today AS DATE)
              AND r.review_date <= CAST(:today AS DATE) + CAST(:days AS INTEGER)
            ORDER BY r.review_date ASC
            LIMIT 20
        """, {"today": today, "days": days})


def get_system_health() -> dict:
    """系统健康检查：stale preparing、error、无知识节点 session、低分 session。"""
    # stale preparing
    stale = get_stale_preparing_sessions(10)
    
    # error sessions
    errors = _fetch_all("""
        SELECT COUNT(*) AS n FROM sessions WHERE status = 'error'
    """)
    
    # sessions without knowledge node (non-completed)
    no_node = _fetch_all("""
        SELECT COUNT(*) AS n FROM sessions
        WHERE knowledge_node_id IS NULL AND status NOT IN ('completed', 'error')
    """)
    
    # low-score completed sessions (<30)
    low_score = _fetch_all("""
        SELECT COUNT(*) AS n FROM sessions
        WHERE status = 'completed' AND score > 0 AND score < 30
    """)
    
    # parse failures in recent rounds
    parse_fails = _fetch_all("""
        SELECT COUNT(*) AS n FROM rounds
        WHERE CAST(eval_json AS TEXT) LIKE '%parse_failed%'
    """)
    
    return {
        "stale_preparing": stale["count"],
        "error_sessions": errors[0]["n"] if errors else 0,
        "no_knowledge_node": no_node[0]["n"] if no_node else 0,
        "low_score": low_score[0]["n"] if low_score else 0,
        "parse_failures": parse_fails[0]["n"] if parse_fails else 0,
        "ok": stale["count"] == 0,
    }


# ── Knowledge Tree (end of section) ───────────────────────────────────────

def get_sessions_by_node(node_id: str, limit: int = 50) -> list[dict]:
    """Get sessions bound to a specific knowledge node."""
    return _fetch_all(
        "SELECT * FROM sessions WHERE knowledge_node_id = :nid ORDER BY created_at DESC LIMIT :lim",
        {"nid": node_id, "lim": limit}
    )


# ── Knowledge tree (file-based) ────────────────────────────────────────────────

def get_knowledge_tree() -> list:
    if not KNOWLEDGE_TREE_PATH.exists():
        return []
    try:
        return json.loads(KNOWLEDGE_TREE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


# ── Maintenance: State Machine Invariants ───────────────────────────────────────

def check_invariants(stale_minutes: int = 10) -> dict:
    """检查状态机一致性，返回所有违规项的列表。
    
    Returns: {
        "ok": bool,
        "issues": [{"type": str, "severity": "error"|"warn", "detail": str, "ids": [...]}]
    }
    """
    issues = []
    
    # 1. pending feynman rounds but session status != 'feynman'
    rows = _fetch_all("""
        SELECT DISTINCT s.id, s.title, s.status, COUNT(r.id) AS pending_count
        FROM sessions s
        JOIN rounds r ON r.session_id = s.id
        WHERE r.type = 'feynman' AND r.status = 'pending'
          AND s.status != 'feynman'
        GROUP BY s.id, s.title, s.status
    """)
    if rows:
        issues.append({
            "type": "pending_feynman_wrong_status",
            "severity": "error",
            "detail": f"{len(rows)} session(s) have pending feynman rounds but status != 'feynman'",
            "ids": [r["id"] for r in rows],
            "sessions": [{"id": r["id"], "title": r.get("title",""), "status": r["status"], "pending_count": r["pending_count"]} for r in rows],
        })
    
    # 2. completed with feynman rounds but no review_report
    rows = _fetch_all("""
        SELECT DISTINCT s.id, s.title
        FROM sessions s
        JOIN rounds r ON r.session_id = s.id
        WHERE r.type = 'feynman' AND r.status = 'completed'
          AND s.status = 'completed'
          AND (s.review_report IS NULL OR s.review_report::text = 'null')
    """)
    if rows:
        issues.append({
            "type": "completed_missing_review_report",
            "severity": "warn",
            "detail": f"{len(rows)} completed session(s) with feynman rounds but no review_report",
            "ids": [r["id"] for r in rows],
        })
    
    # 3. error sessions without error_msg
    rows = _fetch_all("""
        SELECT id, title FROM sessions
        WHERE status = 'error' AND (error_msg IS NULL OR error_msg = '')
    """)
    if rows:
        issues.append({
            "type": "error_without_msg",
            "severity": "warn",
            "detail": f"{len(rows)} error session(s) without error_msg",
            "ids": [r["id"] for r in rows],
        })
    
    # 4. Multiple pending feynman groups per session
    rows = _fetch_all("""
        SELECT session_id, COUNT(DISTINCT group_id) AS n_groups
        FROM rounds
        WHERE type = 'feynman' AND status = 'pending' AND group_id IS NOT NULL
        GROUP BY session_id
        HAVING COUNT(DISTINCT group_id) > 1
    """)
    if rows:
        issues.append({
            "type": "multiple_pending_feynman_groups",
            "severity": "error",
            "detail": f"{len(rows)} session(s) have multiple pending feynman groups",
            "ids": [r["session_id"] for r in rows],
            "groups": [{"session_id": r["session_id"], "n_groups": r["n_groups"]} for r in rows],
        })
    
    # 5. Multiple pending review schedules per session
    rows = _fetch_all("""
        SELECT session_id, COUNT(*) AS n
        FROM review_schedule
        WHERE status = 'pending'
        GROUP BY session_id
        HAVING COUNT(*) > 1
    """)
    if rows:
        issues.append({
            "type": "multiple_pending_review_schedules",
            "severity": "warn",
            "detail": f"{len(rows)} session(s) have multiple pending review schedules",
            "ids": [r["session_id"] for r in rows],
        })
    
    # 6. Stale preparing sessions
    stale_data = get_stale_preparing_sessions(stale_minutes)
    stale_rows = stale_data.get("stale", [])
    if stale_rows:
        issues.append({
            "type": "stale_preparing",
            "severity": "warn",
            "detail": f"{len(stale_rows)} session(s) stuck in 'preparing' for >{stale_minutes}min",
            "ids": [r["id"] for r in stale_rows],
        })
    
    # 7. Completed with score=0 but no review report (suspicious manual complete)
    rows = _fetch_all("""
        SELECT id, title FROM sessions
        WHERE status = 'completed' AND score = 0 AND (review_report IS NULL OR review_report::text = 'null')
    """)
    if rows:
        issues.append({
            "type": "completed_zero_score",
            "severity": "warn",
            "detail": f"{len(rows)} completed session(s) with score=0 (manually completed?)",
            "ids": [r["id"] for r in rows],
        })
    
    errors = [i for i in issues if i["severity"] == "error"]
    return {
        "ok": len(errors) == 0,
        "total_issues": len(issues),
        "error_count": len(errors),
        "warn_count": len(issues) - len(errors),
        "issues": issues,
    }


def repair_invariants(dry_run: bool = True) -> dict:
    """修复常见的状态机不一致问题。
    
    - pending feynman rounds + status != feynman → 修正 status 为 'feynman'
    """
    repairs = []
    
    # Fix: pending feynman but status != feynman
    with _tx() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT s.id AS session_id, s.status AS current_status
            FROM sessions s
            JOIN rounds r ON r.session_id = s.id
            WHERE r.type = 'feynman' AND r.status = 'pending'
              AND s.status != 'feynman'
        """)).fetchall()
        
        for row in rows:
            sid = row._mapping["session_id"]
            old_status = row._mapping["current_status"]
            if not dry_run:
                conn.execute(
                    text("UPDATE sessions SET status = 'feynman', updated_at = :ts WHERE id = :sid"),
                    {"sid": sid, "ts": _now_str()}
                )
            repairs.append({
                "session_id": sid,
                "old_status": old_status,
                "new_status": "feynman",
                "dry_run": dry_run,
            })
    
    return {"dry_run": dry_run, "repairs": repairs, "count": len(repairs)}


if __name__ == "__main__":
    init_db()
