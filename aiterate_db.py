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

        # learning_gaps — Phase 5: independent gap entity with status tracking
        if sqlite:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS learning_gaps (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id          INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source_round_id     INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
                text                TEXT    NOT NULL,
                concept_tags        TEXT    NOT NULL DEFAULT '[]',
                severity            TEXT    NOT NULL DEFAULT 'medium',
                status              TEXT    NOT NULL DEFAULT 'open',
                resolved_by_round_id INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
                recurrence_count    INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
                resolved_at         TEXT
            )"""))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS learning_gaps (
                id                  SERIAL PRIMARY KEY,
                session_id          INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source_round_id     INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
                text                TEXT    NOT NULL,
                concept_tags        {jb}    NOT NULL DEFAULT '[]',
                severity            TEXT    NOT NULL DEFAULT 'medium',
                status              TEXT    NOT NULL DEFAULT 'open',
                resolved_by_round_id INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
                recurrence_count    INTEGER NOT NULL DEFAULT 0,
                created_at          {ts}    NOT NULL DEFAULT NOW(),
                resolved_at         {ts}
            )"""))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_learning_gaps_session ON learning_gaps(session_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_learning_gaps_status ON learning_gaps(status)"
            ))

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

    print(f"[DB] aiterate ready — {cfg.get('type','postgresql')} — sessions / rounds / profile / review_schedule / learning_gaps / jobs")


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

# Phase 4.2: 默认评分标准（可被用户通过 settings 自定义覆盖）
_DEFAULT_RUBRICS = {
    "review_explain": (
        "你是一位学习导师，正在评估学习者对已学知识的间隔复习效果。\n"
        "\n"
        "学习者之前学过某个主题，现在隔了一段时间重新用自己的话解释。\n"
        "请从以下维度评估：\n"
        "\n"
        "1. 概念的准确性（是否理解正确）\n"
        "2. 表达的完整性（是否涵盖核心要点）\n"
        "3. 理解的深度（是否停留在表面）\n"
        "\n"
        "请输出 JSON：\n"
        '{\n'
        '  "score": <0-100 整数，60以上=基本掌握，80以上=熟练掌握>,\n'
        '  "praise": "<做得好的方面，1-2句>",\n'
        '  "gap": "<需要加强的地方，1-2句>",\n'
        '  "verdict": "<一句话总结评价>"\n'
        "}"
    ),
    "feynman": (
        "你是一位费曼学习法的导师，通过提问检验学习者对知识的理解深度。\n"
        "\n"
        "学习者已经完成了对某个主题的初始学习和深化追问，现在你需要：\n"
        "1. 生成 3-5 道渐进式问题（从浅到深）\n"
        "2. 评估学习者的回答质量\n"
        "\n"
        "生成问题输出 JSON：\n"
        '{\n'
        '  "questions": ["问题1", "问题2", ...]\n'
        "}\n"
        "\n"
        "评估回答输出 JSON：\n"
        '{\n'
        '  "answers": [{"score": 0-100, "comment": "评价"}, ...],\n'
        '  "final_score": 0-100,\n'
        '  "summary": "一句话总结"\n'
        "}"
    ),
    "deepen_evaluate": (
        "你是一位学习导师，正在评估学习者的总结和对概念的深入探索。\n"
        "\n"
        "请从以下维度评估：\n"
        "1. 总结是否抓住了核心概念\n"
        "2. 追问是否触及该主题的深层原理\n"
        "\n"
        "输出 JSON：\n"
        '{\n'
        '  "score": <0-5 整数>,\n'
        '  "comment": "<一句话评价>",\n'
        '  "suggestion": "<建议的下一步方向>"\n'
        "}"
    ),
}

def get_profile() -> dict:
    r = _fetch_one("SELECT * FROM profile WHERE id = :id", {"id": PROFILE_ID})
    if not r:
        return {"id": PROFILE_ID, "theme": "night", "settings": {}}
    r["settings"] = _jload(r.get("settings") or {})
    if not isinstance(r["settings"], dict):
        r["settings"] = {}
    return r

def get_settings() -> dict:
    s = get_profile().get("settings") or {}

    # Phase 4.2: 注入默认 rubrics（如果用户未自定义）
    if "rubrics" not in s:
        s["rubrics"] = dict(_DEFAULT_RUBRICS)
    else:
        # Merge: 用户可能只覆盖了部分 role
        for role, rubric in _DEFAULT_RUBRICS.items():
            if role not in s["rubrics"]:
                s["rubrics"][role] = rubric

    # Phase 4.2: rubric_version 自动递增（当 rubrics 首次存在或发生变化时）
    # 这个值由 upsert_rubric 管理，get_settings 只读取
    if "rubric_version" not in s:
        s["rubric_version"] = 1

    return s


def get_rubric(role: str) -> dict:
    """Phase 4.2: 获取指定 role 的评分标准（含版本信息）。"""
    settings = get_settings()
    rubrics = settings.get("rubrics", {})
    rubric = rubrics.get(role, _DEFAULT_RUBRICS.get(role, ""))
    version = settings.get("rubric_version", 1)
    return {
        "content": rubric if isinstance(rubric, str) else rubric.get("system", ""),
        "version": version,
        "role": role,
    }


def upsert_rubric(role: str, system_prompt: str) -> dict:
    """Phase 4.2: 更新某个 role 的 rubric，自动递增版本号。"""
    settings = get_settings()
    if "rubrics" not in settings:
        settings["rubrics"] = {}

    settings["rubrics"][role] = system_prompt
    settings["rubric_version"] = settings.get("rubric_version", 0) + 1

    upsert_profile(**{"settings__rubrics": settings["rubrics"],
                       "settings__rubric_version": settings["rubric_version"]})
    return get_rubric(role)


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

# ── Learning Gaps (Phase 5) ─────────────────────────────────────────────────

def create_gaps_from_take(session_id: int, round_id: int, eval_json: dict) -> list[dict]:
    """Extract gaps from a take round's eval_json and persist as learning_gaps.
    
    Deduplication: only creates gaps for text not already open in this session.
    Returns the list of created gap dicts.
    """
    gaps_text = eval_json.get("gaps") or []
    if not gaps_text:
        return []
    
    # Get existing open gap texts for this session
    existing = _fetch_all(
        "SELECT text FROM learning_gaps WHERE session_id = :sid AND status = 'open'",
        {"sid": session_id}
    )
    existing_texts = {r["text"] for r in existing}
    
    created = []
    for g in gaps_text:
        g_text = str(g).strip()
        if not g_text or g_text in existing_texts:
            continue
        gid = _insert_returning_id("""
            INSERT INTO learning_gaps (session_id, source_round_id, text, severity)
            VALUES (:sid, :rid, :txt, 'medium') RETURNING id
        """, {"sid": session_id, "rid": round_id, "txt": g_text})
        gap = {
            "id": gid, "session_id": session_id, "source_round_id": round_id,
            "text": g_text, "status": "open", "severity": "medium",
            "concept_tags": [], "recurrence_count": 0, "resolved_by_round_id": None,
            "created_at": _now_str(), "resolved_at": None
        }
        created.append(gap)
    return created


def get_session_gaps(session_id: int, status: str = None) -> list[dict]:
    """Get gaps for a session, optionally filtered by status."""
    if status:
        rows = _fetch_all(
            "SELECT * FROM learning_gaps WHERE session_id = :sid AND status = :st ORDER BY created_at DESC",
            {"sid": session_id, "st": status}
        )
    else:
        rows = _fetch_all(
            "SELECT * FROM learning_gaps WHERE session_id = :sid ORDER BY created_at DESC",
            {"sid": session_id}
        )
    for r in rows:
        r["concept_tags"] = _jload(r.get("concept_tags") or [])
    return rows


def get_unresolved_gaps(session_id: int) -> list[dict]:
    """Backward-compatible: return unresolved gaps for workspace payload.
    
    Looks in learning_gaps first (Phase 5), falls back to old round.eval_json extraction.
    """
    rows = _fetch_all(
        """SELECT id, session_id, source_round_id, text, severity, status,
                  concept_tags, resolved_by_round_id, recurrence_count, created_at, resolved_at
           FROM learning_gaps
           WHERE session_id = :sid AND status IN ('open', 'reappeared')
           ORDER BY created_at DESC""",
        {"sid": session_id}
    )
    
    if rows:
        # New format from learning_gaps table
        gaps = []
        for r in rows:
            gaps.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "source_round_id": r["source_round_id"],
                "gap": r["text"],
                "text": r["text"],
                "severity": r["severity"],
                "status": r["status"],
                "concept_tags": _jload(r.get("concept_tags") or []),
                "resolved_by_round_id": r.get("resolved_by_round_id"),
                "recurrence_count": r.get("recurrence_count", 0),
                "created_at": r.get("created_at"),
                "resolved_at": r.get("resolved_at"),
            })
        return gaps
    
    # Fallback: extract from old rounds.eval_json (backward compat)
    rounds = _fetch_all(
        """SELECT id, seq, eval_json, created_at FROM rounds
           WHERE session_id = :sid AND type = 'take'
           ORDER BY seq DESC""",
        {"sid": session_id}
    )
    gaps = []
    for r in rounds:
        ev = _jload(r.get("eval_json")) if r.get("eval_json") else {}
        for g_text in (ev.get("gaps") or []):
            gaps.append({
                "round_id": r["id"],
                "seq": r["seq"],
                "gap": g_text,
                "praise": ev.get("praise", ""),
                "created_at": r.get("created_at"),
            })
    return gaps


def update_gap(gap_id: int, **kwargs) -> bool:
    """Update gap fields. Returns True if a row was updated."""
    if "concept_tags" in kwargs and isinstance(kwargs["concept_tags"], list):
        if _is_sqlite():
            kwargs["concept_tags"] = json.dumps(kwargs["concept_tags"], ensure_ascii=False)
        else:
            kwargs["concept_tags"] = json.dumps(kwargs["concept_tags"], ensure_ascii=False)
    
    sets = [f"{k} = :{k}" for k in kwargs]
    params = {**kwargs, "gid": gap_id}
    _exec(f"UPDATE learning_gaps SET {', '.join(sets)} WHERE id = :gid", params)
    return True


def resolve_gap(gap_id: int, resolved_by_round_id: int = None) -> dict:
    """Mark a gap as resolved."""
    with _tx() as conn:
        conn.execute(text(
            "UPDATE learning_gaps SET status = 'resolved',"
            " resolved_by_round_id = :rrid, resolved_at = :ts WHERE id = :gid"
        ), {"gid": gap_id, "rrid": resolved_by_round_id, "ts": _now_str()})
    return {"id": gap_id, "status": "resolved"}


def reopen_gap(gap_id: int) -> dict:
    """Mark a gap as reappeared (e.g., from feynman weak_points or review failure)."""
    with _tx() as conn:
        conn.execute(text(
            "UPDATE learning_gaps SET status = 'reappeared', recurrence_count = recurrence_count + 1,"
            " resolved_at = NULL WHERE id = :gid"
        ), {"gid": gap_id})
    return {"id": gap_id, "status": "reappeared"}


def sync_gaps_from_weak_points(session_id: int, weak_points: list[str]) -> list[dict]:
    """Sync feynman/review weak_points into the gap ledger.
    
    For each weak point: look for matching open/resolved gaps and reopen them,
    or create new gaps if no match.
    Returns list of affected gaps.
    """
    affected = []
    for wp in weak_points:
        wp_text = str(wp).strip()
        if not wp_text:
            continue
        
        # Try fuzzy match: find gap containing this text or vice versa
        existing = _fetch_one(
            """SELECT id, status, recurrence_count FROM learning_gaps
               WHERE session_id = :sid
                 AND (text ILIKE :wp1 OR :wp2 ILIKE '%' || text || '%')
               LIMIT 1""",
            {"sid": session_id, "wp1": f"%{wp_text}%", "wp2": wp_text}
        )
        
        if existing and existing["status"] in ("resolved", "ignored"):
            reopen_gap(existing["id"])
            affected.append({"id": existing["id"], "action": "reopened", "text": wp_text})
        elif existing and existing["status"] in ("open", "reappeared"):
            affected.append({"id": existing["id"], "action": "already_open", "text": wp_text})
        else:
            # Create new gap
            gid = _insert_returning_id("""
                INSERT INTO learning_gaps (session_id, text, severity, status)
                VALUES (:sid, :txt, 'high', 'open') RETURNING id
            """, {"sid": session_id, "txt": wp_text})
            affected.append({"id": gid, "action": "created", "text": wp_text})
    
    return affected


def get_gap_stats(session_id: int = None) -> dict:
    """Get gap statistics: open, resolved, total, by severity."""
    where = "WHERE session_id = :sid" if session_id else ""
    params = {"sid": session_id} if session_id else {}
    
    rows = _fetch_all(f"""
        SELECT status, severity, COUNT(*) AS n
        FROM learning_gaps {where}
        GROUP BY status, severity ORDER BY status, severity
    """, params)
    
    stats = {"open": 0, "resolved": 0, "ignored": 0, "reappeared": 0, "total": 0}
    for r in rows:
        stats[r["status"]] = stats.get(r["status"], 0) + r["n"]
        stats["total"] += r["n"]
    
    return stats


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


# ── Knowledge Tree Mastery (Phase 5) ─────────────────────────────────────────

def _collect_node_ids(tree: list, node_id: str) -> set:
    """Collect a node's id and all descendant ids from the tree."""
    ids = {node_id}
    for node in tree:
        if node["id"] == node_id:
            stack = [node]
            while stack:
                n = stack.pop()
                for child in n.get("children", []):
                    ids.add(child["id"])
                    stack.append(child)
            break
        found = _collect_node_ids(node.get("children", []), node_id)
        if found:
            ids.update(found)
            break
    return ids


def get_knowledge_tree_mastery() -> list[dict]:
    """Compute per-node mastery stats: score, status, gaps, reviews, prerequisites.
    
    Returns the knowledge tree with mastery fields added to each node.
    The returned structure mirrors knowledge_tree.json but each node gets:
      { mastery_score, status, total_sessions, completed_sessions, avg_score,
        gap_count, review_due_count, low_score_count, 
        prerequisites (child IDs from tree), last_activity }
    """
    tree = get_knowledge_tree()
    if not tree:
        return []
    
    # Get flat list of all node IDs
    def flatten(nodes, result):
        for n in nodes:
            result.append({"id": n["id"], "title": n["title"], "parent": None})
            for c in n.get("children", []):
                flatten_children(c, n["id"], result)
    
    def flatten_children(node, parent_id, result):
        result.append({"id": node["id"], "title": node["title"], "parent": parent_id})
        for c in node.get("children", []):
            flatten_children(c, node["id"], result)
    
    flat = []
    for domain in tree:
        flatten([domain], flat)
    
    # Build id → descendant_ids map using the tree structure
    def collect_descendants(node, ancestor_ids=None):
        if ancestor_ids is None:
            ancestor_ids = []
        all_ids = set()
        for n in node.get("children", []):
            all_ids.add(n["id"])
            all_ids.update(collect_descendants(n, [n["id"]]))
        return all_ids
    
    node_descendants = {}
    for domain in tree:
        node_descendants[domain["id"]] = collect_descendants(domain)
        stack = list(domain.get("children", []))
        while stack:
            n = stack.pop()
            node_descendants[n["id"]] = collect_descendants(n)
            stack.extend(n.get("children", []))
    
    # Build id_set → stats map (node_id + all descendants)
    from datetime import date
    today = date.today().isoformat()
    
    # Get all sessions with knowledge_node_id
    all_sessions = _fetch_all(
        "SELECT id, knowledge_node_id, status, score, updated_at FROM sessions WHERE knowledge_node_id IS NOT NULL"
    )
    
    # Get gap counts per session
    gap_rows = _fetch_all(
        "SELECT session_id, COUNT(*) AS n FROM learning_gaps WHERE status IN ('open', 'reappeared') GROUP BY session_id"
    )
    session_gaps = {r["session_id"]: r["n"] for r in gap_rows}
    
    # Get due review counts per session
    review_rows = _fetch_all(
        "SELECT r.session_id, COUNT(*) AS n FROM review_schedule r WHERE r.status = 'pending' AND r.review_date <= :today GROUP BY r.session_id",
        {"today": today}
    )
    session_reviews = {r["session_id"]: r["n"] for r in review_rows}
    
    # Compute per-node stats
    node_stats = {}
    for ni in flat:
        node_id = ni["id"]
        descendant_ids = node_descendants.get(node_id, set()) | {node_id}
        
        # Filter sessions for this node and descendants
        matching = [s for s in all_sessions if s["knowledge_node_id"] in descendant_ids]
        
        total = len(matching)
        completed = sum(1 for s in matching if s["status"] == "completed")
        scores = [s["score"] for s in matching if s["score"] is not None and s["score"] > 0]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
        
        gap_count = sum(session_gaps.get(s["id"], 0) for s in matching)
        review_due = sum(session_reviews.get(s["id"], 0) for s in matching)
        low_score_count = sum(1 for s in matching if s.get("score") and s["score"] > 0 and s["score"] < 40)
        
        last_activity = max((s["updated_at"] for s in matching if s.get("updated_at")), default=None)
        
        # Compute mastery_score: weighted combo of completion rate + avg score
        if total == 0:
            mastery_score = 0
            status = "unseen"
        else:
            completion_rate = completed / total if total > 0 else 0
            score_norm = avg_score / 100 if avg_score > 0 else 0
            mastery_score = round((completion_rate * 50 + score_norm * 50))
            
            if mastery_score >= 80:
                status = "mastered"
            elif mastery_score >= 60:
                status = "reviewing"
            elif mastery_score >= 40:
                status = "learning"
            elif mastery_score >= 20:
                status = "weak"
            else:
                status = "unseen"
        
        node_stats[node_id] = {
            "node_id": node_id,
            "title": ni["title"],
            "mastery_score": mastery_score,
            "status": status,
            "total_sessions": total,
            "completed_sessions": completed,
            "avg_score": avg_score,
            "gap_count": gap_count,
            "review_due_count": review_due,
            "low_score_count": low_score_count,
            "last_activity": str(last_activity) if last_activity else None,
        }
    
    # Build result tree with mastery stats
    def enrich_node(node):
        nid = node["id"]
        stats = node_stats.get(nid, {"mastery_score": 0, "status": "unseen"})
        enriched = {
            **{k: v for k, v in node.items() if k not in ("children",)},
            "mastery_score": stats["mastery_score"],
            "status": stats["status"],
            "total_sessions": stats.get("total_sessions", 0),
            "completed_sessions": stats.get("completed_sessions", 0),
            "avg_score": stats.get("avg_score", 0.0),
            "gap_count": stats.get("gap_count", 0),
            "review_due_count": stats.get("review_due_count", 0),
            "low_score_count": stats.get("low_score_count", 0),
            "last_activity": stats.get("last_activity"),
            "children": [enrich_node(c) for c in node.get("children", [])],
        }
        # Prerequisites: child node IDs
        enriched["prerequisites"] = [c["id"] for c in node.get("children", [])]
        return enriched
    
    return [enrich_node(domain) for domain in tree]


# ── Smart Recommendation (Phase 5) ─────────────────────────────────────────

def get_recommended_nodes(limit: int = 3) -> list[dict]:
    """Recommend next learning nodes based on priority:
    1. 逾期复习优先 (due reviews)
    2. 待费曼优先 (feynman pending)
    3. 低分节点优先 (low_score_count > 0)
    4. gap 多的节点优先
    5. mastered 节点的后继节点
    """
    mastery = get_knowledge_tree_mastery()
    
    def flatten_mastery(nodes, result):
        for n in nodes:
            result.append(n)
            flatten_mastery(n.get("children", []), result)
    
    flat = []
    flatten_mastery(mastery, flat)
    
    # Sort by priority
    def priority(n):
        score = 0
        if n.get("review_due_count", 0) > 0:
            score += 10000 + n["review_due_count"] * 100
        if n.get("status") == "learning" or n.get("total_sessions", 0) > 0:
            if n.get("low_score_count", 0) > 0:
                score += 5000 + n["low_score_count"] * 50
            if n.get("gap_count", 0) > 0:
                score += 3000 + n["gap_count"] * 20
            score += n.get("mastery_score", 0)  # lower mastery = higher need
        # Prerequisite nodes: if this is mastered, score its children
        if n.get("status") == "mastered" and n.get("prerequisites"):
            # Don't score the mastered node itself high, but let children bubble up
            pass
        # Unseen nodes with prerequisites met
        if n.get("status") == "unseen":
            score += -100  # Don't prioritize unseen unless nothing else
        
        return -score  # Negative for descending sort
    
    scored = sorted(
        [(n, priority(n)) for n in flat if n.get("total_sessions", 0) > 0],
        key=lambda x: x[1]
    )
    
    result = []
    seen = set()
    for n, _ in scored:
        nid = n.get("id", n.get("node_id"))
        if nid not in seen and len(result) < limit:
            result.append({
                "node_id": nid,
                "title": n.get("title", ""),
                "status": n.get("status"),
                "mastery_score": n.get("mastery_score", 0),
                "total_sessions": n.get("total_sessions", 0),
                "gap_count": n.get("gap_count", 0),
                "review_due_count": n.get("review_due_count", 0),
            })
            seen.add(nid)
    
    # Fallback: if no active nodes, suggest the shallowest unseen nodes
    if not result:
        for n in flat:
            nid = n.get("id", n.get("node_id"))
            if nid not in seen and len(result) < limit:
                result.append({
                    "node_id": nid,
                    "title": n.get("title", ""),
                    "status": "unseen",
                    "mastery_score": 0,
                    "total_sessions": n.get("total_sessions", 0),
                    "gap_count": 0,
                    "review_due_count": 0,
                })
                seen.add(nid)
    
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


# ── Phase 4.1: 个性化难度系数 ──────────────────────────────────────────

def _get_session_review_scores(session_id: int) -> list[int]:
    """获取某个 session 的历史复习分数（按时间升序）。"""
    rows = _fetch_all(
        "SELECT review_score FROM review_schedule "
        "WHERE session_id = :sid AND review_score IS NOT NULL "
        "ORDER BY completed_at ASC",
        {"sid": session_id}
    )
    return [r["review_score"] for r in rows]


def _compute_difficulty_factor(session_id: int, current_score: int | None) -> float:
    """Phase 4.1: 基于历史复习表现计算个性化难度系数。

    算法：
    - 取最近 3 次复习分数（含当前）的加权平均
    - avg >= 80: 因子 1.5（拉长间隔，掌握得好）
    - avg >= 60: 因子 1.0（标准）
    - avg >= 40: 因子 0.7（缩短间隔，薄弱）
    - avg <  40: 因子 0.5（紧急，频繁复习）

    同时考虑知识节点聚合（如果 session 绑定了 knowledge_node）：
    节点下所有 session 的复习均分也参与计算，session:node = 0.6:0.4 加权。
    """
    scores = _get_session_review_scores(session_id)

    # 合并历史分数 + 当前分数
    all_scores = list(scores)
    if current_score is not None:
        all_scores.append(current_score)

    if not all_scores:
        return 1.0  # 无历史数据，默认标准间隔

    # 最近 3 次加权（越近权重越高）
    recent = all_scores[-3:]
    weights = list(range(1, len(recent) + 1))  # [1, 2, 3] 或 [1, 2] 或 [1]
    session_avg = sum(s * w for s, w in zip(recent, weights)) / sum(weights)

    # Session 级因子
    if session_avg >= 80:
        session_factor = 1.5
    elif session_avg >= 60:
        session_factor = 1.0
    elif session_avg >= 40:
        session_factor = 0.7
    else:
        session_factor = 0.5

    # 尝试获取知识节点聚合
    session = _fetch_one(
        "SELECT knowledge_node_id FROM sessions WHERE id = :sid",
        {"sid": session_id}
    )
    node_id = session.get("knowledge_node_id") if session else None

    if node_id:
        # 查询该节点下所有 session 的复习均分
        node_row = _fetch_one("""
            SELECT AVG(rs.review_score)::float AS node_avg
            FROM review_schedule rs
            JOIN sessions s ON s.id = rs.session_id
            WHERE s.knowledge_node_id = :nid AND rs.review_score IS NOT NULL
        """, {"nid": node_id})
        node_avg = node_row["node_avg"] if node_row and node_row["node_avg"] is not None else None

        if node_avg is not None:
            if node_avg >= 80:
                node_factor = 1.5
            elif node_avg >= 60:
                node_factor = 1.0
            elif node_avg >= 40:
                node_factor = 0.7
            else:
                node_factor = 0.5
            # session:node = 0.6:0.4
            return round(session_factor * 0.6 + node_factor * 0.4, 2)
        else:
            return session_factor

    return session_factor


def schedule_review(session_id: int, score: int | None) -> int | None:
    """创建复习排期（个性化艾宾浩斯遗忘曲线，Phase 4.1）。

    基础间隔（艾宾浩斯曲线）：
    - R1: 1天  R2: 2天  R3: 6天  R4: 31天  R5: 90天

    个性化调制：
    1. 历史表现难度系数（_compute_difficulty_factor）：0.5~1.5
       - 高分历史 → 拉长间隔；低分历史 → 缩短间隔
    2. 即时分数调制：
       - score < 40: 明天立即重来（1天）
       - score 40-60: 间隔 × 0.6（加速）
       - score >= 60: 正常应用难度系数
    3. 最小 1 天，最大 base × 2.0（防过度拉长）

    已有 pending 排期时跳过，返回 None。
    """
    from datetime import date, timedelta
    import math

    # 检查是否已有 pending 排期
    existing = _fetch_one(
        "SELECT id FROM review_schedule WHERE session_id = :sid AND status = 'pending'",
        {"sid": session_id}
    )
    if existing:
        return None

    # 统计已完成复习次数 → 决定下一轮基础间隔
    completed = _fetch_one(
        "SELECT COUNT(*) AS n FROM review_schedule WHERE session_id = :sid AND status = 'completed'",
        {"sid": session_id}
    )
    review_round = (completed["n"] if completed else 0)  # 0 = 首次复习

    # 基础间隔
    if review_round >= len(_EBBINGHAUS_INTERVALS):
        base_days = _EBBINGHAUS_INTERVALS[-1]
    else:
        base_days = _EBBINGHAUS_INTERVALS[review_round]

    # ── 个性化调制 ──
    difficulty = _compute_difficulty_factor(session_id, score)

    if score is not None and score < 40:
        # 极低分：紧急复习，明天再来
        days = 1
    elif score is not None and score < 60:
        # 中低分：加速复习
        days = max(1, round(base_days * difficulty * 0.6))
    else:
        # 正常或高分：用难度系数
        days = max(1, round(base_days * difficulty))

    # 上限保护：不超过 base × 2.0
    days = min(days, max(1, round(base_days * 2.0)))

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

    # 5. 推荐下一个知识节点：Phase 5 智能推荐
    next_node_rows = get_recommended_nodes(3)

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


# ── Phase 4.3: Weekly Learning Report ─────────────────────────────────

def get_weekly_report_data() -> dict:
    """聚合本周学习数据，用于生成周报。"""
    from datetime import date, timedelta
    today = date.today()
    week_start = (today - timedelta(days=7)).isoformat()
    today_str = today.isoformat()

    # 1. 本周会话
    sessions_created = _fetch_one(
        "SELECT COUNT(*) AS n FROM sessions WHERE created_at >= :ws",
        {"ws": week_start}
    )["n"]

    sessions_completed = _fetch_one(
        "SELECT COUNT(*) AS n FROM sessions WHERE status = 'completed' AND updated_at >= :ws",
        {"ws": week_start}
    )["n"]

    # 2. 本周复习
    reviews_completed = _fetch_one(
        "SELECT COUNT(*) AS n FROM review_schedule WHERE status = 'completed' AND completed_at >= :ws",
        {"ws": week_start}
    )["n"]

    review_avg = _fetch_one(
        "SELECT AVG(review_score)::float AS avg FROM review_schedule "
        "WHERE review_score IS NOT NULL AND completed_at >= :ws",
        {"ws": week_start}
    )
    review_avg_score = round(review_avg["avg"], 1) if review_avg and review_avg["avg"] else None

    reviews_pending = _fetch_one(
        "SELECT COUNT(*) AS n FROM review_schedule WHERE status = 'pending' AND review_date <= :today",
        {"today": today_str}
    )["n"]

    # 3. 薄弱点
    open_gaps = _fetch_one(
        "SELECT COUNT(*) AS n FROM learning_gaps WHERE status = 'open'",
    )["n"]

    # 4. 知识节点掌握度变化（本周有活动的节点）
    active_nodes = _fetch_all("""
        SELECT DISTINCT s.knowledge_node_id
        FROM sessions s
        WHERE s.knowledge_node_id IS NOT NULL AND s.updated_at >= :ws
    """, {"ws": week_start})

    # 5. 推荐学习节点
    recommended = get_recommended_nodes(limit=3)

    # 6. 本周完成的 session 标题
    recent_done = _fetch_all(
        "SELECT id, title, score FROM sessions WHERE status = 'completed' AND updated_at >= :ws ORDER BY updated_at DESC LIMIT 5",
        {"ws": week_start}
    )

    return {
        "week_start": week_start,
        "week_end": today_str,
        "sessions_created": sessions_created,
        "sessions_completed": sessions_completed,
        "reviews_completed": reviews_completed,
        "review_avg_score": review_avg_score,
        "reviews_pending": reviews_pending,
        "open_gaps": open_gaps,
        "active_node_ids": [n["knowledge_node_id"] for n in active_nodes],
        "recommended": recommended,
        "recent_done": [dict(r) for r in recent_done],
    }


if __name__ == "__main__":
    init_db()
