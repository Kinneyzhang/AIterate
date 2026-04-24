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
            return {**_DEFAULT_DB_CFG, **raw}
        except Exception:
            pass
    return dict(_DEFAULT_DB_CFG)

def save_db_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    merged = {**load_db_config(), **cfg}
    DB_CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

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

def _exec(sql: str, params=None):
    """执行不返回结果的 SQL"""
    with get_engine().begin() as conn:
        conn.execute(text(sql), params or {})

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
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT        NOT NULL,
                content    TEXT,
                type       TEXT        NOT NULL DEFAULT 'question',
                status     TEXT        NOT NULL DEFAULT 'preparing',
                material   TEXT,
                score      INTEGER,
                error_msg  TEXT,
                created_at TEXT        NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT        NOT NULL DEFAULT (datetime('now'))
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
                error_msg  TEXT,
                created_at {ts} NOT NULL DEFAULT NOW(),
                updated_at {ts} NOT NULL DEFAULT NOW()
            )"""))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC)"
            ))

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

    # 迁移旧格式 settings（幂等）
    _migrate_settings()

    print(f"[DB] aiterate ready — {cfg.get('type','postgresql')} — sessions / rounds / profile")


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
        VALUES (:id, :theme, :settings::jsonb, NOW())
        ON CONFLICT (id) DO UPDATE
            SET theme=EXCLUDED.theme, settings=EXCLUDED.settings, updated_at=NOW()
        """, {"id": PROFILE_ID, "theme": theme, "settings": s_json})

    return get_profile()


# ── Sessions ───────────────────────────────────────────────────────────────────

def create_session(title: str, content: str = "", type: str = "question") -> int:
    if _is_sqlite():
        return _insert_returning_id("""
        INSERT INTO sessions (title, content, type, status)
        VALUES (:title, :content, :type, 'preparing') RETURNING id
        """, {"title": title, "content": content, "type": type})
    else:
        return _insert_returning_id("""
        INSERT INTO sessions (title, content, type, status)
        VALUES (:title, :content, :type, 'preparing') RETURNING id
        """, {"title": title, "content": content, "type": type})

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


# ── Knowledge tree (file-based) ────────────────────────────────────────────────

def get_knowledge_tree() -> list:
    if not KNOWLEDGE_TREE_PATH.exists():
        return []
    try:
        return json.loads(KNOWLEDGE_TREE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


if __name__ == "__main__":
    init_db()
