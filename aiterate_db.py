"""
AIIterate Database Layer — PostgreSQL
Tables: sessions, rounds, profile
"""
import json
import os
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Connection ─────────────────────────────────────────────

PG_HOST     = os.environ.get("AITERATE_PG_HOST",     "127.0.0.1")
PG_PORT     = int(os.environ.get("AITERATE_PG_PORT", "5432"))
PG_DBNAME   = os.environ.get("AITERATE_PG_DBNAME",   "aiterate")
PG_USER     = os.environ.get("AITERATE_PG_USER",     "geekinney")
PG_PASSWORD = os.environ.get("AITERATE_PG_PASSWORD", "")

CONFIG_DIR           = Path(__file__).parent / "config"
KNOWLEDGE_TREE_PATH  = CONFIG_DIR / "knowledge_tree.json"
PROFILE_ID           = "default"

# ── Helpers ────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DBNAME,
        user=PG_USER, password=PG_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )

def _q(conn, sql, params=None):
    c = conn.cursor()
    c.execute(sql, params or ())
    return c

def row(r):
    return dict(r) if r else None

def rows(rs):
    return [dict(r) for r in rs]

def _now():
    return datetime.now().isoformat()

def _jlist(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            r = json.loads(v)
            return r if isinstance(r, list) else []
        except Exception:
            return []
    return []


# ── Schema ─────────────────────────────────────────────────

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # 学习会话
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id          SERIAL PRIMARY KEY,
        title       TEXT        NOT NULL,
        content     TEXT,
        type  TEXT        NOT NULL DEFAULT 'question',
        status      TEXT        NOT NULL DEFAULT 'preparing',
        material     TEXT,
        score       SMALLINT,
        error_msg   TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC)")

    # 轮次（会话内每一轮人机交互）
    c.execute("""
    CREATE TABLE IF NOT EXISTS rounds (
        id         SERIAL PRIMARY KEY,
        session_id INTEGER     NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        seq        SMALLINT    NOT NULL,
        type       TEXT        NOT NULL,  -- take | press | feynman
        input      TEXT,                  -- take/press: 用户文本; feynman: AI题目(JSON)
        output     TEXT,                  -- take/press: AI回复; feynman: 用户作答(JSON)
        eval_json  JSONB,                 -- 已废弃，保留兼容
        score_comment TEXT,               -- feynman: 单题评价文字
        group_id   INTEGER,               -- feynman: 同一轮出题的 group 标识（= 该组第一题 id）
        score      SMALLINT,              -- take/feynman 有分; press 无
        status     TEXT        NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (session_id, seq)
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id)")

    # 用户配置（单行）
    # settings 结构：
    # {
    #   "llm": {
    #     "provider": "", "base_url": "", "api_key": "", "model": "",
    #     "roles": {
    #       "title":    {"provider":"","base_url":"","api_key":"","model":""},
    #       "answer":   {...},
    #       "evaluate": {...},
    #       "review":   {...},
    #       "deepen":   {...}
    #     }
    #   },
    #   "tavily_api_key": ""
    # }
    c.execute("""
    CREATE TABLE IF NOT EXISTS profile (
        id         TEXT        PRIMARY KEY DEFAULT 'default',
        theme      TEXT        NOT NULL DEFAULT 'night',
        settings   JSONB       NOT NULL DEFAULT '{}',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)

    # 删除旧列（幂等）
    for col in ("goal_mins",):
        try:
            c.execute(f"ALTER TABLE profile DROP COLUMN IF EXISTS {col}")
        except Exception:
            pass

    # 新增列（幂等）
    try:
        c.execute("ALTER TABLE rounds ADD COLUMN IF NOT EXISTS score_comment JSONB")
    except Exception:
        pass

    # 插入默认 profile（幂等）
    c.execute("""
    INSERT INTO profile (id) VALUES ('default')
    ON CONFLICT (id) DO NOTHING
    """)

    conn.commit()

    # 迁移旧 flat settings → 新嵌套结构
    _migrate_settings(conn)

    conn.close()
    print("[DB] aiterate ready — sessions / rounds / profile")


_LLM_ROLES = ["title", "answer", "evaluate", "review", "deepen"]

def _migrate_settings(conn):
    """将旧的 flat key 格式迁移到新嵌套结构（幂等）"""
    c = conn.cursor()
    c.execute("SELECT settings FROM profile WHERE id = %s", (PROFILE_ID,))
    row_ = c.fetchone()
    if not row_:
        return
    raw = row_["settings"]
    if isinstance(raw, str):
        try:
            s = json.loads(raw)
        except Exception:
            s = {}
    else:
        s = dict(raw) if raw else {}

    # 如果已经是新格式（有 "llm" key），不迁移
    if "llm" in s:
        return

    # 构建新结构
    llm = {
        "provider": s.get("llm_default_provider", ""),
        "base_url":  s.get("llm_default_base_url", ""),
        "api_key":   s.get("llm_default_api_key", ""),
        "model":     s.get("llm_default_model", ""),
        "roles": {},
    }
    for role in _LLM_ROLES:
        role_cfg = {
            "provider": s.get(f"llm_{role}_provider", ""),
            "base_url":  s.get(f"llm_{role}_base_url", ""),
            "api_key":   s.get(f"llm_{role}_api_key", ""),
            "model":     s.get(f"llm_{role}_model", ""),
        }
        # 只写有值的 role
        if any(role_cfg.values()):
            llm["roles"][role] = role_cfg

    new_settings = {
        "llm": llm,
        "tavily_api_key": s.get("tavily_api_key", ""),
    }

    c.execute(
        "UPDATE profile SET settings = %s, updated_at = NOW() WHERE id = %s",
        (json.dumps(new_settings), PROFILE_ID),
    )
    conn.commit()
    print("[DB] settings migrated to nested format")


# ── Profile ────────────────────────────────────────────────

def get_profile() -> dict:
    conn = get_conn()
    r = _q(conn, "SELECT * FROM profile WHERE id = %s", (PROFILE_ID,)).fetchone()
    conn.close()
    if not r:
        return {"id": PROFILE_ID, "theme": "night", "settings": {}}
    p = dict(r)
    if isinstance(p.get("settings"), str):
        p["settings"] = json.loads(p["settings"])
    return p

def get_settings() -> dict:
    """返回 profile.settings 字典（热读，每次从 DB 取）"""
    p = get_profile()
    return p.get("settings") or {}


def upsert_profile(**kwargs) -> dict:
    """
    支持字段：
      theme          → 直接写列
      settings       → 覆盖整个 settings JSONB
      settings__llm  → 合并 settings.llm
      settings__tavily_api_key → 写 settings.tavily_api_key
    """
    conn = get_conn()
    cur = get_profile()
    settings = dict(cur.get("settings") or {})

    direct = {}
    for k, v in kwargs.items():
        if k.startswith("settings__"):
            key = k[10:]
            if key == "llm" and isinstance(v, dict):
                existing_llm = settings.get("llm", {})
                existing_llm.update(v)
                settings["llm"] = existing_llm
            else:
                settings[key] = v
        else:
            direct[k] = v

    theme = direct.get("theme", cur["theme"])
    if "settings" in direct:
        settings.update(direct["settings"])

    _q(conn, """
    INSERT INTO profile (id, theme, settings, updated_at)
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT (id) DO UPDATE
        SET theme = EXCLUDED.theme,
            settings = EXCLUDED.settings,
            updated_at = NOW()
    """, (PROFILE_ID, theme, json.dumps(settings)))
    conn.commit()
    conn.close()
    return get_profile()


# ── Sessions ───────────────────────────────────────────────

def create_session(title: str, content: str = "", type: str = "question") -> int:
    conn = get_conn()
    row_id = _q(conn, """
    INSERT INTO sessions (title, content, type, status)
    VALUES (%s, %s, %s, 'preparing') RETURNING id
    """, (title, content, type)).fetchone()["id"]
    conn.commit()
    conn.close()
    return row_id

def get_session(session_id: int) -> dict | None:
    conn = get_conn()
    r = _q(conn, "SELECT * FROM sessions WHERE id = %s", (session_id,)).fetchone()
    conn.close()
    if not r:
        return None
    return dict(r)

def get_recent_sessions(limit: int = 20) -> list[dict]:
    conn = get_conn()
    rs = _q(conn, """
    SELECT * FROM sessions ORDER BY created_at DESC LIMIT %s
    """, (limit,)).fetchall()
    conn.close()
    return rows(rs)

def update_session(session_id: int, **kwargs):
    kwargs["updated_at"] = "NOW()" 
    set_parts = []
    vals = []
    for k, v in kwargs.items():
        if v == "NOW()":
            set_parts.append(f"{k} = NOW()")
        else:
            set_parts.append(f"{k} = %s")
            vals.append(v)
    vals.append(session_id)
    conn = get_conn()
    _q(conn, f"UPDATE sessions SET {', '.join(set_parts)} WHERE id = %s", vals)
    conn.commit()
    conn.close()

def get_stats() -> dict:
    conn = get_conn()
    total     = _q(conn, "SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    completed = _q(conn, "SELECT COUNT(*) AS n FROM sessions WHERE status = 'completed'").fetchone()["n"]
    avg_score = _q(conn, "SELECT ROUND(AVG(score)::numeric, 1) AS v FROM sessions WHERE score IS NOT NULL").fetchone()["v"]
    recent    = _q(conn, """
    SELECT DATE(created_at) AS d, COUNT(*) AS n
    FROM sessions WHERE created_at >= NOW() - INTERVAL '7 days'
    GROUP BY d ORDER BY d
    """).fetchall()
    conn.close()
    return {
        "total_sessions":     total,
        "completed_sessions": completed,
        "avg_score":          float(avg_score) if avg_score else 0.0,
        "recent_7days":       rows(recent),
    }


# ── Rounds ─────────────────────────────────────────────────

def next_seq(session_id: int) -> int:
    """取该 session 当前最大 seq + 1，并发安全"""
    conn = get_conn()
    row = _q(conn,
        "SELECT COALESCE(MAX(seq), 0) AS m FROM rounds WHERE session_id = %s",
        (session_id,)).fetchone()
    return (row["m"] if row else 0) + 1

def create_round(session_id: int, seq: int, type: str,
                 input: str | None = None,
                 output: str | None = None,
                 score: int | None = None,
                 status: str = "pending") -> int:
    """
    type=take/press : input=用户文本, output=AI回复
    type=feynman    : input=单道题目文字, output=用户作答文字, group_id=同组第一题id
    """
    conn = get_conn()
    row_id = _q(conn, """
    INSERT INTO rounds (session_id, seq, type, input, output, score, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (session_id, seq, type, input, output, score, status)).fetchone()["id"]
    conn.commit()
    conn.close()
    return row_id

def get_rounds(session_id: int) -> list[dict]:
    conn = get_conn()
    rs = _q(conn, "SELECT * FROM rounds WHERE session_id = %s ORDER BY seq", (session_id,)).fetchall()
    conn.close()
    return rows(rs)

def get_pending_feynman_group(session_id: int) -> list[dict]:
    """返回最近一组 pending 的 feynman rounds（按 group_id 聚合）"""
    conn = get_conn()
    rs = _q(conn, """
    SELECT * FROM rounds
    WHERE session_id = %s AND type = 'feynman' AND status = 'pending'
    ORDER BY seq
    """, (session_id,)).fetchall()
    conn.close()
    return rows(rs)

def update_round(round_id: int, **kwargs):
    # feynman input/output 若传 list，序列化为 JSON 字符串
    for key in ("input", "output"):
        if key in kwargs and isinstance(kwargs[key], list):
            kwargs[key] = json.dumps(kwargs[key], ensure_ascii=False)
    fields = ", ".join(f"{k} = %s" for k in kwargs)
    vals   = list(kwargs.values()) + [round_id]
    conn = get_conn()
    _q(conn, f"UPDATE rounds SET {fields} WHERE id = %s", vals)
    conn.commit()
    conn.close()


# ── Knowledge tree (file-based, no DB) ────────────────────

def get_knowledge_tree() -> list:
    if not KNOWLEDGE_TREE_PATH.exists():
        return []
    try:
        return json.loads(KNOWLEDGE_TREE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []





if __name__ == "__main__":
    init_db()
