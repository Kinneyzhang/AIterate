"""
AIIterate FastAPI Backend
Port: 7070
"""
import asyncio
import json
import logging
import re
import secrets
from html import unescape
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import urlparse

import aiohttp

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator

import sys
sys.path.insert(0, str(Path(__file__).parent))
import aiterate_db as db
import aiterate_ai as ai

logger = logging.getLogger("aiterate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

FRONTEND = Path(__file__).parent / "dist" / "index.html"
ASSETS_DIR = Path(__file__).parent / "dist" / "assets"
VENDOR_DIR = Path(__file__).parent / "dist" / "vendor"

app = FastAPI(title="AIIterate API", version="3.0.0")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/vendor", StaticFiles(directory=str(VENDOR_DIR)), name="vendor")


# ── Auth System (Phase 4.3: Cookie-based session auth) ─────

AUTH_COOKIE_NAME = "aiterate_session"
# In-memory session store (survives until restart; for local use this is fine)
_active_sessions: dict[str, str] = {}  # token → "authenticated"


def _generate_session_token() -> str:
    return secrets.token_hex(32)


async def _require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
    aiterate_session: Annotated[str | None, Cookie()] = None,
):
    # 1. Cookie-based session (Phase 4.3)
    if aiterate_session and aiterate_session in _active_sessions:
        return True

    # 2. Header-based token (backward compat)
    if x_admin_token and db.check_admin_token(x_admin_token):
        return True

    raise HTTPException(401, "Missing or invalid admin token")


# ── Auth Endpoints (Phase 4.3) ──────────────────────────────

class LoginRequest(BaseModel):
    token: str


@app.post("/api/auth/login")
async def auth_login(body: LoginRequest, response: Response):
    """验证 admin token，设置 session cookie。"""
    if not db.check_admin_token(body.token):
        raise HTTPException(401, "Invalid token")

    session_token = _generate_session_token()
    _active_sessions[session_token] = "authenticated"

    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,  # 30 days
    )
    return {"ok": True, "message": "Logged in"}


@app.post("/api/auth/logout")
async def auth_logout(
    request: Request,
    response: Response,
    aiterate_session: Annotated[str | None, Cookie()] = None,
):
    """清除 session cookie。"""
    if aiterate_session:
        _active_sessions.pop(aiterate_session, None)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"ok": True, "message": "Logged out"}


@app.get("/api/auth/status")
async def auth_status(
    aiterate_session: Annotated[str | None, Cookie()] = None,
    x_admin_token: Annotated[str | None, Header()] = None,
):
    """检查当前认证状态。"""
    if aiterate_session and aiterate_session in _active_sessions:
        return {"authenticated": True, "method": "cookie"}
    if x_admin_token and db.check_admin_token(x_admin_token):
        return {"authenticated": True, "method": "header"}
    return {"authenticated": False}


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    msg = str(exc)
    # 友好化常见错误
    if "No API key" in msg or "api_key" in msg.lower():
        user_msg = "⚠️ 尚未配置大模型 API Key，请先到「设置」中填写。"
    elif "Tavily" in msg and "not configured" in msg:
        user_msg = "⚠️ 尚未配置 Tavily API Key，请先到「设置 → 联网搜索」中填写。"
    elif "401" in msg or "Unauthorized" in msg:
        user_msg = "❌ API Key 无效或已过期，请在「设置」中重新填写。"
    elif "model" in msg.lower() and ("not found" in msg.lower() or "404" in msg):
        user_msg = "❌ 模型名称不正确，请在「设置」中检查 Model 字段。"
    else:
        user_msg = f"❌ AI 服务异常：{msg[:200]}"
    return JSONResponse(status_code=400, content={"detail": user_msg})


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "service": "aiterate",
        "frontend": FRONTEND.exists(),
        "db_type": db.load_db_config().get("type", "unknown"),
        "version": "3.0.0",
    }


@app.get("/favicon.svg")
async def favicon():
    favicon_path = Path(__file__).parent / "dist" / "favicon.svg"
    if not favicon_path.exists():
        favicon_path = Path(__file__).parent / "assets" / "favicon.svg"
    return FileResponse(favicon_path, media_type="image/svg+xml")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.31.222:7070",
        "http://localhost:7070",
        "http://127.0.0.1:7070",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _session_phase(status: str | None) -> str:
    return {
        "preparing": "preparing",
        "learning":  "learning",
        "deepening": "deepening",
        "revising":  "revising",
        "feynman":   "feynman",
        "completed": "completed",
        "error":     "error",
    }.get(status or "", "preparing")


def _build_session_workspace_payload(session: dict, rounds: list[dict]) -> dict:
    phase = _session_phase(session.get("status"))
    current_review_group = []   # 当前待答的一组 feynman rounds
    latest_review_result = None

    feynman_rounds = [r for r in rounds if r.get("type") == "feynman"]
    pending = [r for r in feynman_rounds if r.get("status") == "pending"]
    done    = [r for r in feynman_rounds if r.get("status") == "completed"]

    if pending:
        current_review_group = pending
    if done:
        # 按 group_id 聚合，取最后一组
        by_group: dict[int, list] = {}
        for r in done:
            gid = r.get("group_id") or r["id"]
            by_group.setdefault(gid, []).append(r)
        latest_gid = max(by_group.keys())
        latest_review_result = sorted(by_group[latest_gid], key=lambda x: x["seq"])

    # 收集 take round 的 eval_json（含 gaps/praise）
    take_rounds_with_eval = []
    for r in rounds:
        if r.get("type") == "take":
            ev = db._jload(r.get("eval_json")) if r.get("eval_json") else {}
            if ev:
                take_rounds_with_eval.append({
                    "id": r["id"], "seq": r["seq"],
                    "score": r.get("score"), "input": r.get("input"),
                    "eval": ev,
                })

    # 汇总所有 gaps
    gaps = db.get_unresolved_gaps(session["id"])
    review_report = db.get_review_report(session["id"])
    knowledge_node_id = db.get_knowledge_node(session["id"])
    review_schedule = db.get_session_review_schedule(session["id"])

    payload = {
        "session": session,
        "rounds": rounds,
        "phase": phase,
        "current_review_group":  current_review_group,
        "latest_review_result":  latest_review_result,
        "take_evaluations":      take_rounds_with_eval,
        "unresolved_gaps":       gaps,
        "review_report":         review_report,
        "review_schedule":       review_schedule,
        "knowledge_node_id":     knowledge_node_id,
    }

    # 如果有知识节点 ID，注入节点详情
    if knowledge_node_id:
        tree = db.get_knowledge_tree()
        node = db.find_node_by_id(tree, knowledge_node_id)
        if node:
            payload["knowledge_node"] = {
                "id": node.get("id"),
                "title": node.get("title"),
                "keywords": node.get("keywords", []),
                "prompt_fragments": node.get("prompt_fragments", []),
            }

    return payload


@app.on_event("startup")
async def startup():
    db.init_db()
    # Phase 4: 恢复重启时丢失的 running jobs
    try:
        recovered = db.recover_stale_jobs(timeout_minutes=2)
        if recovered["recovered_jobs"] > 0:
            print(f"[AIIterate] Job recovery: {recovered['recovered_jobs']} jobs reset to pending")
        if recovered["stuck_sessions"]:
            print(f"[AIIterate] ⚠ {len(recovered['stuck_sessions'])} sessions stuck in preparing, will be recovered by worker")
    except Exception as e:
        print(f"[AIIterate] Job recovery failed (non-fatal): {e}")

    # Also handle legacy: sessions stuck in preparing without a job (pre-Phase 4 data)
    try:
        stale = db.get_stale_preparing_sessions(timeout_minutes=5)
        if stale["count"] > 0:
            from datetime import datetime, timezone, timedelta
            retried = 0
            errored = 0
            for s in stale["stale"]:
                try:
                    created = s.get("created_at", "")
                    is_recent = True
                    if created:
                        try:
                            ct = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            age = datetime.now(timezone.utc) - ct
                            is_recent = age < timedelta(minutes=10)
                        except Exception:
                            pass
                    if is_recent:
                        # Create a job to recover this session
                        db.create_job(
                            "generate_session_answer",
                            {"session_id": s["id"], "content": s.get("content", ""),
                             "type": s.get("type", "question"), "web_search": s.get("web_search", False),
                             "knowledge_node_id": s.get("knowledge_node_id")},
                        )
                        retried += 1
                    else:
                        db.update_session(s["id"], status="error",
                                         error_msg="Background task lost (too old to retry)")
                        errored += 1
                except Exception as e:
                    db.update_session(s["id"], status="error", error_msg=f"Startup retry failed: {e}")
                    errored += 1
            if retried or errored:
                print(f"[AIIterate] Legacy stale preparing: {retried} enqueued, {errored} marked error")
    except Exception as e:
        print(f"[AIIterate] Legacy stale check failed (non-fatal): {e}")

    # 启动后台 job worker
    asyncio.create_task(_job_worker())
    print("[AIIterate] DB ready + job worker started")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup connections on shutdown."""
    try:
        await ai.close_http_session()
        print("[AIIterate] HTTP session closed")
    except Exception as e:
        print(f"[AIIterate] Shutdown cleanup error (non-fatal): {e}")


@app.get("/")
async def serve_frontend():
    token = db.get_or_create_admin_token()
    html = FRONTEND.read_text(encoding="utf-8")
    if "%%AITERATE_TOKEN%%" in html:
        html = html.replace("%%AITERATE_TOKEN%%", token)
    else:
        # Backward-compatible fallback for accidentally built empty-token shells.
        html = html.replace('window.AITERATE_TOKEN=""', f"window.AITERATE_TOKEN={json.dumps(token)}")
    return HTMLResponse(content=html)


# ── Profile ───────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    theme: Optional[str] = None  # "night" | "mono"


_LLM_ROLES = ["title", "answer", "evaluate", "review", "deepen", "question"]


class LLMRoleConfig(BaseModel):
    provider: Optional[str] = None
    base_url:  Optional[str] = None
    api_key:   Optional[str] = None
    model:     Optional[str] = None

class LLMConfig(BaseModel):
    provider: Optional[str] = None
    base_url:  Optional[str] = None
    api_key:   Optional[str] = None
    model:     Optional[str] = None
    roles:     Optional[dict[str, LLMRoleConfig]] = None  # keyed by role name

class SettingsUpdate(BaseModel):
    llm:               Optional[LLMConfig] = None
    tavily_api_key:    Optional[str]       = None
    feynman_pass_score: Optional[int]      = None
    inbox_sources:      Optional[dict]     = None


class KnowledgeSelectionUpdate(BaseModel):
    selected_nodes: list[str]


# ── DB Config ──────────────────────────────────────────────

class DbConfigUpdate(BaseModel):
    type:         Optional[str] = None   # sqlite | postgresql | mysql | oracle
    host:         Optional[str] = None
    port:         Optional[int] = None
    dbname:       Optional[str] = None
    user:         Optional[str] = None
    password:     Optional[str] = None
    sqlite_path:  Optional[str] = None
    service_name: Optional[str] = None  # oracle only

@app.get("/api/db-config", dependencies=[Depends(_require_admin)])
async def get_db_config():
    cfg = db.load_db_config()
    safe = dict(cfg)
    if safe.get("password"):
        safe["password"] = "••••••"
    return safe

@app.put("/api/db-config", dependencies=[Depends(_require_admin)])
async def update_db_config(body: DbConfigUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "no fields to update")
    # 拒绝未实现的数据库类型
    if updates.get("type") in ("mysql", "oracle"):
        raise HTTPException(400, "MySQL/Oracle 尚未实现，请使用 sqlite 或 postgresql")
    # 先用候选配置测试连接，成功再落盘
    test_result = db.test_db_config(updates)
    if not test_result["ok"]:
        raise HTTPException(400, f"DB 连接测试失败：{test_result['error']}")
    db.save_db_config(updates)
    db.init_engine()
    return {"ok": True}


@app.get("/api/knowledge-tree", dependencies=[Depends(_require_admin)])
async def get_knowledge_tree():
    return {"tree": db.get_knowledge_tree()}


@app.get("/api/profile", dependencies=[Depends(_require_admin)])
async def get_profile():
    p = db.get_profile()
    return {"id": p["id"], "theme": p["theme"], "updated_at": p.get("updated_at")}


@app.patch("/api/profile", dependencies=[Depends(_require_admin)])
async def update_profile(body: ProfileUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "theme" in updates and updates["theme"] not in {"night", "mono"}:
        raise HTTPException(400, "theme must be night or mono")
    return db.upsert_profile(**updates)


# ── Helpers ──────────────────────────────────────────────

def _mask_key(key: str) -> str:
    """sk-abc123...xyz789 -> sk-...xyz789"""
    if not key:
        return ""
    if len(key) <= 8:
        return key[:3] + "..." + key[-2:]
    return key[:3] + "..." + key[-4:]

_KEY_CLEAR_SENTINEL = "__CLEAR__"


def _safe_llm_dict(llm: dict) -> dict:
    """Return LLM config for frontend: replace raw keys with masked + flag."""
    raw_key = llm.get("api_key", "")
    roles_raw = llm.get("roles") or {}
    safe_roles = {}
    for role in _LLM_ROLES:
        rcfg = roles_raw.get(role, {})
        rkey = rcfg.get("api_key", "")
        safe_roles[role] = {
            "provider": rcfg.get("provider", ""),
            "base_url": rcfg.get("base_url", ""),
            "api_key_masked": _mask_key(rkey),
            "has_api_key": bool(rkey),
            "model": rcfg.get("model", ""),
        }
    return {
        "provider": llm.get("provider", ""),
        "base_url": llm.get("base_url", ""),
        "api_key_masked": _mask_key(raw_key),
        "has_api_key": bool(raw_key),
        "model": llm.get("model", ""),
        "roles": safe_roles,
    }


# ── Settings ──────────────────────────────────────────────

@app.get("/api/settings", dependencies=[Depends(_require_admin)])
async def get_settings():
    settings = db.get_settings()
    llm = settings.get("llm") or {}
    tavily_raw = settings.get("tavily_api_key", "")
    return {
        "llm": _safe_llm_dict(llm),
        "tavily_api_key_masked": _mask_key(tavily_raw),
        "has_tavily_api_key": bool(tavily_raw),
        "feynman_pass_score": settings.get("feynman_pass_score", 60),
        "inbox_sources": settings.get("inbox_sources") or {"telegram_sources": []},
    }


@app.patch("/api/settings", dependencies=[Depends(_require_admin)])
async def update_settings(body: SettingsUpdate):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return await get_settings()

    existing = db.get_settings()
    kwargs = {}

    if "llm" in updates:
        new_llm = updates["llm"]
        existing_llm = existing.get("llm") or {}

        def _merge_keys(base: dict, overlay: dict) -> dict:
            r = dict(base)
            for k in ("api_key",):
                v = overlay.get(k)
                if v == _KEY_CLEAR_SENTINEL:
                    r[k] = ""
                elif v and v.strip():
                    r[k] = v
            for k in ("provider", "base_url", "model"):
                if k in overlay and overlay[k] is not None:
                    r[k] = overlay[k]
            return r

        merged = _merge_keys(existing_llm, new_llm)
        new_roles = new_llm.get("roles") or {}
        existing_roles = existing_llm.get("roles") or {}
        merged_roles = {}
        for role in _LLM_ROLES:
            base = existing_roles.get(role, {})
            over = new_roles.get(role, {})
            merged_roles[role] = _merge_keys(base, over)
        merged["roles"] = merged_roles
        kwargs["settings__llm"] = merged

    if "tavily_api_key" in updates:
        v = updates["tavily_api_key"]
        if v == _KEY_CLEAR_SENTINEL:
            kwargs["settings__tavily_api_key"] = ""
        elif v and v.strip():
            kwargs["settings__tavily_api_key"] = v

    if "feynman_pass_score" in updates:
        score = max(1, min(100, int(updates["feynman_pass_score"])))
        kwargs["settings__feynman_pass_score"] = score

    if "inbox_sources" in updates:
        raw_sources = updates.get("inbox_sources") or {}
        raw_telegram = raw_sources.get("telegram_sources") or []
        cleaned = []
        if isinstance(raw_telegram, list):
            for item in raw_telegram[:20]:
                if isinstance(item, str):
                    label = item.strip()
                    source = item.strip()
                elif isinstance(item, dict):
                    label = str(item.get("label") or "").strip()
                    source = str(item.get("source") or item.get("url") or "").strip()
                else:
                    continue
                if source:
                    cleaned.append({"label": label[:80] or source[:80], "source": source[:200]})
        kwargs["settings__inbox_sources"] = {"telegram_sources": cleaned}

    if kwargs:
        db.upsert_profile(**kwargs)
    return await get_settings()


@app.get("/api/ready", dependencies=[Depends(_require_admin)])
async def get_ready():
    """返回当前配置是否就绪（LLM、Tavily）"""
    settings = db.get_settings()
    llm_ok    = bool((settings.get("llm") or {}).get("api_key", ""))
    tavily_ok = bool(settings.get("tavily_api_key", ""))
    return {"llm": llm_ok, "tavily": tavily_ok}


# ── Stats ─────────────────────────────────────────────────

@app.get("/api/stats", dependencies=[Depends(_require_admin)])
async def get_stats():
    return db.get_stats()


# ── Inbox ──────────────────────────────────────────────────

class InboxCreate(BaseModel):
    content: str
    source_type: str = "text"
    direction: str | None = None

    @field_validator("content")
    @classmethod
    def inbox_content_valid(cls, v):
        if not v or not v.strip():
            raise ValueError("内容不能为空")
        v = v.strip()
        if len(v) > 10000:
            raise ValueError(f"内容过长（{len(v)} 字符），最多 10000 字符")
        return v

    @field_validator("source_type")
    @classmethod
    def source_type_valid(cls, v):
        v = (v or "text").strip() or "text"
        if len(v) > 40:
            raise ValueError("source_type 过长")
        return v

    @field_validator("direction")
    @classmethod
    def create_direction_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2000:
            raise ValueError("方向描述过长，最多 2000 字符")
        return v or None


class InboxUrlExtractRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_valid(cls, v):
        v = (v or "").strip()
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("请输入有效的 http/https 链接")
        if len(v) > 1000:
            raise ValueError("链接过长")
        return v


def _compact_text(text: str, limit: int = 9000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit].strip()


def _extract_html_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if not m:
        return ""
    return _compact_text(unescape(re.sub(r"<[^>]+>", " ", m.group(1))), 120)


def _html_to_readable_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html or "", flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<(p|div|section|article|h[1-6]|li|br)[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    lines = [_compact_text(line, 600) for line in text.splitlines()]
    lines = [line for line in lines if len(line) >= 12]
    return "\n".join(lines)[:9000].strip()


@app.post("/api/inbox/extract-url", dependencies=[Depends(_require_admin)])
async def extract_inbox_url(body: InboxUrlExtractRequest):
    headers = {"User-Agent": "AIIterate/3.0 (+local learning inbox)"}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(body.url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise HTTPException(400, f"链接抓取失败：HTTP {resp.status}")
                content_type = resp.headers.get("content-type", "")
                raw = await resp.text(errors="ignore")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"链接抓取失败：{type(exc).__name__}") from exc

    if "html" in content_type.lower() or "<html" in raw[:1000].lower():
        title = _extract_html_title(raw)
        text = _html_to_readable_text(raw)
    else:
        title = ""
        text = _compact_text(raw, 9000)
    if not text:
        raise HTTPException(400, "没有从链接中提取到可读文本")
    return {"url": body.url, "title": title, "content": text}


class InboxRegenerateRequest(BaseModel):
    direction: str | None = None

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2000:
            raise ValueError("方向描述过长，最多 2000 字符")
        return v or None


class InboxQuestionSelectRequest(BaseModel):
    web_search: bool = False
    knowledge_node_id: str | None = None


@app.get("/api/inbox", dependencies=[Depends(_require_admin)])
async def list_inbox(limit: int = 50):
    return db.get_inbox_items(limit=max(1, min(200, limit)))


@app.post("/api/inbox", dependencies=[Depends(_require_admin)])
async def create_inbox_item(body: InboxCreate):
    item_id = db.create_inbox_item(body.content, body.source_type)
    db.create_job(
        job_type="generate_inbox_questions",
        payload={"inbox_item_id": item_id, "content": body.content, "direction": body.direction, "replace": True},
    )
    return {"id": item_id, "status": "pending"}


@app.get("/api/inbox/{item_id}", dependencies=[Depends(_require_admin)])
async def get_inbox_item(item_id: int):
    item = db.get_inbox_item(item_id)
    if not item:
        raise HTTPException(404, "Inbox item not found")
    return {"item": item, "questions": db.get_inbox_questions(item_id)}


@app.post("/api/inbox/{item_id}/regenerate", dependencies=[Depends(_require_admin)])
async def regenerate_inbox_questions(item_id: int, body: InboxRegenerateRequest = InboxRegenerateRequest()):
    item = db.get_inbox_item(item_id)
    if not item:
        raise HTTPException(404, "Inbox item not found")
    db.update_inbox_item(item_id, status="pending", error_msg=None)
    db.create_job(
        job_type="generate_inbox_questions",
        payload={
            "inbox_item_id": item_id,
            "content": item.get("content", ""),
            "direction": body.direction,
            "replace": True,
        },
    )
    return {"ok": True, "id": item_id, "status": "pending"}


@app.post("/api/inbox/{item_id}/archive", dependencies=[Depends(_require_admin)])
async def archive_inbox(item_id: int):
    if not db.archive_inbox_item(item_id):
        raise HTTPException(404, "Inbox item not found")
    return {"ok": True, "status": "archived"}


@app.post("/api/inbox/questions/{question_id}/select", dependencies=[Depends(_require_admin)])
async def select_inbox_question(question_id: int, body: InboxQuestionSelectRequest = InboxQuestionSelectRequest()):
    question = db.get_inbox_question(question_id)
    if not question:
        raise HTTPException(404, "Inbox question not found")
    if question.get("status") == "selected" and question.get("session_id"):
        return {"session_id": question["session_id"], "question_id": question_id, "reused": True}
    item = db.get_inbox_item(question["inbox_item_id"])
    if not item:
        raise HTTPException(404, "Inbox item not found")

    content = (
        f"问题：{question['question']}\n\n"
        f"来源素材：\n{item.get('content', '')}\n\n"
        f"AI 生成问题理由：\n{question.get('why') or '这个问题值得进一步学习和验证。'}"
    )
    temp_title = question["question"][:40].strip()
    sid = db.create_session(temp_title, content, "question", web_search=body.web_search)
    db.update_session(sid, status="preparing")
    if body.knowledge_node_id:
        db.set_knowledge_node(sid, body.knowledge_node_id)
    db.mark_inbox_question_selected(question_id, sid)
    db.create_job(
        job_type="generate_session_answer",
        payload={
            "session_id": sid,
            "content": content,
            "type": "question",
            "web_search": body.web_search,
            "knowledge_node_id": body.knowledge_node_id,
        },
    )
    return {"session_id": sid, "question_id": question_id}


@app.post("/api/inbox/questions/{question_id}/ignore", dependencies=[Depends(_require_admin)])
async def ignore_inbox_question(question_id: int):
    if not db.get_inbox_question(question_id):
        raise HTTPException(404, "Inbox question not found")
    return {"ok": True, "question": db.ignore_inbox_question(question_id)}


# ── Sessions ──────────────────────────────────────────────

@app.get("/api/sessions", dependencies=[Depends(_require_admin)])
async def get_sessions(limit: int = 200):
    return db.get_recent_sessions(limit=limit)


class SessionCreate(BaseModel):
    content: str                        # 用户完整输入，title 由 AI 生成
    type: str = "question"        # question / viewpoint
    web_search: bool = False            # 是否联网搜索
    knowledge_node_id: str | None = None  # 绑定知识节点

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("内容不能为空")
        if len(v) > 20000:
            raise ValueError(f"内容过长（{len(v)} 字符），最多 20000 字符")
        return v.strip()

    @field_validator("type")
    @classmethod
    def type_valid(cls, v):
        if v not in ("question", "viewpoint"):
            raise ValueError('type 必须是 question 或 viewpoint')
        return v


class SessionTitleUpdate(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def title_valid(cls, v):
        if not v or not v.strip():
            raise ValueError("标题不能为空")
        v = v.strip()
        if len(v) > 120:
            raise ValueError("标题过长，最多 120 字符")
        return v


class SessionPinUpdate(BaseModel):
    pinned: bool = True


@app.post("/api/sessions", dependencies=[Depends(_require_admin)])
async def create_session_and_answer(body: SessionCreate):
    """阶段1：创建 session，通过 DB job queue 后台异步生成标题+初始回答"""
    # 先用 content 前 40 字作为临时标题，AI 生成正式标题后更新
    temp_title = body.content[:40].strip()
    sid = db.create_session(
        title=temp_title,
        content=body.content,
        type=body.type,
        web_search=body.web_search,
    )
    db.update_session(sid, status="preparing")

    # 如果有知识节点，立即绑定
    if body.knowledge_node_id:
        db.set_knowledge_node(sid, body.knowledge_node_id)

    # 用 DB-backed job queue 替代 BackgroundTasks
    db.create_job(
        job_type="generate_session_answer",
        payload={
            "session_id": sid,
            "content": body.content,
            "type": body.type,
            "web_search": body.web_search,
            "knowledge_node_id": body.knowledge_node_id,
        },
    )

    return {
        "session_id": sid,
        "status": "preparing",
    }


@app.get("/api/sessions/{session_id}", dependencies=[Depends(_require_admin)])
async def get_session(session_id: int):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s


@app.patch("/api/sessions/{session_id}/title", dependencies=[Depends(_require_admin)])
async def rename_session(session_id: int, body: SessionTitleUpdate):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    db.update_session(session_id, title=body.title)
    return {"ok": True, "session": db.get_session(session_id)}


@app.post("/api/sessions/{session_id}/pin", dependencies=[Depends(_require_admin)])
async def pin_session(session_id: int, body: SessionPinUpdate):
    s = db.set_session_pinned(session_id, body.pinned)
    if not s:
        raise HTTPException(404, "Session not found")
    return {"ok": True, "session": s}


@app.delete("/api/sessions/{session_id}", dependencies=[Depends(_require_admin)])
async def delete_session(session_id: int):
    if not db.delete_session(session_id):
        raise HTTPException(404, "Session not found")
    return {"ok": True, "deleted_id": session_id}


@app.get("/api/sessions/{session_id}/share", dependencies=[Depends(_require_admin)])
async def get_session_share(session_id: int):
    data = db.build_session_share_summary(session_id)
    if not data:
        raise HTTPException(404, "Session not found")
    return data


@app.get("/api/sessions/{session_id}/rounds", dependencies=[Depends(_require_admin)])
async def get_rounds(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    rounds = db.get_rounds(session_id)
    return {"session_id": session_id, "rounds": rounds}


@app.get("/api/sessions/{session_id}/workspace", dependencies=[Depends(_require_admin)])
async def get_session_workspace(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    rounds = db.get_rounds(session_id)
    return _build_session_workspace_payload(session, rounds)


class DeepenRequest(BaseModel):
    action_type: str | None = None  # "take" 或 "press"
    content: str | None = None      # take: 用户的理解文本; press: 用户的追问文本
    # 兼容前端旧字段名
    action: str | None = None
    text: str | None = None

    @model_validator(mode='after')
    def normalize_fields(self):
        """兼容前端旧 payload {action, text} 和后端标准 {action_type, content}"""
        if self.action_type is None and self.action is not None:
            self.action_type = self.action
        if self.content is None and self.text is not None:
            self.content = self.text
        if self.action_type is None:
            raise ValueError('缺少 action_type（或旧字段 action）')
        if self.content is None:
            raise ValueError('缺少 content（或旧字段 text）')
        if self.action_type not in ("take", "press"):
            raise ValueError('action_type 必须是 take 或 press')
        if not self.content or not self.content.strip():
            raise ValueError("内容不能为空")
        if len(self.content) > 10000:
            raise ValueError(f"内容过长（{len(self.content)} 字符），最多 10000 字符")
        self.content = self.content.strip()
        return self


@app.post("/api/sessions/{session_id}/deepen", dependencies=[Depends(_require_admin)])
async def deepen(session_id: int, body: DeepenRequest):
    """深化阶段：take(理解) 或 press(追问)"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # Phase 5: state transition guard — only allow deepen in valid states
    st = session.get("status", "")
    if st not in ("learning", "deepening", "revising"):
        raise HTTPException(409, f"Cannot deepen in status '{st}'. Allowed: learning, deepening, revising.")

    original_question = session["title"]
    ai_answer = session.get("material", "")
    rounds = db.get_rounds(session_id)

    if body.action_type == "take":
        eval_result = await ai.evaluate_user_take(original_question, ai_answer, body.content)
        eval_json = {
            "score": eval_result["score"],
            "understood_well": eval_result["understood_well"],
            "praise": eval_result["praise"],
            "gaps": eval_result["gaps"],
            "verdict": eval_result["verdict"],
            "parse_failed": eval_result.get("parse_failed", False),
        }
        rid = db.create_round_with_seq(
            session_id=session_id, type="take",
            input=body.content, output=eval_result["verdict"],
            score=eval_result["score"], status="evaluated",
            eval_json=eval_json,
        )
        db.update_session(session_id, status="deepening")

        # Phase 5: persist gaps to learning_gaps table (with status tracking)
        new_gaps = db.create_gaps_from_take(session_id, rid, eval_json)

        # Phase 5.2: auto-detect if user's take resolved previous gaps
        resolved_before = db.try_resolve_gaps_by_content(session_id, body.content, rid)

        # 基于 gaps 生成追问建议（非阻塞）
        suggestions = []
        if eval_result.get("gaps"):
            try:
                sug_result = await ai.suggest_deepen_prompts(original_question, eval_result["gaps"])
                suggestions = sug_result.get("suggestions", [])
            except Exception:
                pass

        return {
            "round_id": rid,
            "type": "take",
            "score": eval_result["score"],
            "praise": eval_result["praise"],
            "gaps": eval_result["gaps"],
            "verdict": eval_result["verdict"],
            "understood_well": eval_result["understood_well"],
            "suggested_prompts": suggestions,
        }

    elif body.action_type == "press":
        history = [
            {"question": r.get("input", ""), "answer": r.get("output", "")}
            for r in rounds if r.get("type") == "press"
        ]
        answer_result = await ai.answer_followup_question(original_question, ai_answer, body.content, history,
                                                           web_search=session.get("web_search", False))
        rid = db.create_round_with_seq(
            session_id=session_id, type="press",
            input=body.content, output=answer_result["answer"],
            score=None, status="deepening",
        )
        db.update_session(session_id, status="deepening")

        # Phase 5.2: auto-detect gap resolution from user press
        resolved = db.try_resolve_gaps_by_content(session_id, body.content, rid)

        return {
            "round_id": rid,
            "type": "press",
            "answer": answer_result["answer"],
            "gaps_resolved": resolved,
        }

    else:
        raise HTTPException(400, "action_type must be 'take' or 'press'")


# ── Global error handler ────────────────────────────────────────────────

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})

# ── Feynman Phase ───────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/start-feynman", dependencies=[Depends(_require_admin)])
async def start_feynman(session_id: int):
    """费曼阶段：AI生成检验题，每题一条 round"""
    try:
        session = db.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")

        # Phase 5: idempotency — reuse existing pending feynman group first.
        # A previous start call legitimately moves the session to `feynman`; retrying
        # that call must be safe instead of failing the state guard below.
        existing = db.get_pending_feynman_group(session_id)
        if existing:
            group_id = existing[0]["group_id"]
            return {
                "group_id": group_id,
                "round_ids": [r["id"] for r in existing],
                "questions": [r["input"] for r in existing],
                "reused": True,
            }

        # Phase 5: state transition guard — only allow feynman in deepening or revising
        st = session.get("status", "")
        if st not in ("deepening", "revising"):
            raise HTTPException(409, f"Cannot start feynman in status '{st}'. Allowed: deepening, revising.")

        # Phase 5: require at least one take round before feynman
        rounds = db.get_rounds(session_id)
        take_rounds = [r for r in rounds if r.get("type") == "take"]
        if not take_rounds:
            raise HTTPException(409, "Cannot start feynman: no take rounds yet. Write at least one understanding summary first.")
        learning_history = " | ".join([r.get("output", "")[:100] for r in rounds])

        # 注入知识节点上下文
        knowledge_node = None
        node_id = db.get_knowledge_node(session_id)
        if node_id:
            tree = db.get_knowledge_tree()
            knowledge_node = db.find_node_by_id(tree, node_id)

        result = await ai.generate_review_questions(
            session["title"], session.get("material", ""), learning_history,
            knowledge_node=knowledge_node,
        )
        questions = result["questions"]
        try:
            group_id, round_ids = db.create_feynman_group(session_id, questions)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"group_id": group_id, "round_ids": round_ids, "questions": questions}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"start_feynman({session_id}) Unhandled error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Internal error: {e}")


class FeynmanAnswerRequest(BaseModel):
    group_id: int
    answers: list[str]   # 按 round 顺序对应

    @field_validator("answers")
    @classmethod
    def answers_valid(cls, v):
        if not v:
            raise ValueError("answers 不能为空")
        if len(v) > 20:
            raise ValueError(f"最多 20 道题，收到 {len(v)} 个答案")
        for i, ans in enumerate(v):
            if len(ans) > 5000:
                raise ValueError(f"第 {i+1} 个答案过长（{len(ans)} 字符），每题最多 5000 字符")
        return v


@app.post("/api/sessions/{session_id}/complete-feynman", dependencies=[Depends(_require_admin)])
async def complete_feynman(session_id: int, body: FeynmanAnswerRequest):
    """Complete feynman phase: atomically evaluate and persist."""
    try:
        session = db.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")

        # Phase 5: state transition guard — complete_feynman requires feynman status
        st = session.get("status", "")
        if st != "feynman":
            raise HTTPException(409, f"Cannot complete feynman in status '{st}'. Expected: feynman.")

        rounds = db.get_rounds(session_id)
        feynman_rounds = sorted(
            [r for r in rounds if r.get("type") == "feynman" and r.get("group_id") == body.group_id],
            key=lambda r: r["seq"]
        )
        if not feynman_rounds:
            raise HTTPException(404, "Feynman group not found")
        if any(r.get("status") != "pending" for r in feynman_rounds):
            raise HTTPException(409, "This feynman group has already been submitted")
        if len(body.answers) != len(feynman_rounds):
            raise HTTPException(400, f"Expected {len(feynman_rounds)} answers, got {len(body.answers)}")

        questions = [r["input"] for r in feynman_rounds]
        eval_result = await ai.evaluate_review_answers(session["title"], questions, body.answers,
                                                        web_search=session.get("web_search", False))
        pass_score = db.get_settings().get("feynman_pass_score", 60)
        passed = eval_result["final_score"] >= pass_score
        new_status = "completed" if passed else "revising"

        try:
            db.complete_feynman_group(
                session_id=session_id,
                group_id=body.group_id,
                answers=body.answers,
                item_scores=eval_result.get("item_scores", []),
                final_score=eval_result["final_score"],
                new_status=new_status,
            )
        except ValueError as e:
            if "already been submitted" in str(e):
                raise HTTPException(409, str(e))
            raise HTTPException(400, str(e))

        # 持久化完整费曼报告
        report = {
            "final_score":   eval_result["final_score"],
            "mastery_level": eval_result["mastery_level"],
            "strong_points": eval_result["strong_points"],
            "weak_points":   eval_result["weak_points"],
            "final_summary": eval_result["final_summary"],
            "passed":        passed,
            "pass_score":    pass_score,
            "parse_failed":  eval_result.get("parse_failed", False),
        }
        db.save_review_report(session_id, report)

        # Phase 5: sync feynman weak_points into the gap ledger
        if eval_result.get("weak_points"):
            gap_results = db.sync_gaps_from_weak_points(session_id, eval_result["weak_points"])
        else:
            gap_results = []

        # 自动创建复习排期
        db.schedule_review(session_id, eval_result["final_score"])

        # Phase 5: build correction plan for failed feynman
        correction_plan = None
        if not passed:
            correction_plan = {
                "type": "correction_plan",
                "failed_items": eval_result.get("item_scores", []),
                "weak_concepts": eval_result.get("weak_points", []),
                "associated_gaps": gap_results,
                "recommended_actions": [
                    "re-take: rewrite your understanding after fixing the weak points above",
                    "press: ask AI targeted questions about the specific concepts you failed",
                    "review: look at the feynman questions you got wrong and study those concepts",
                ],
                "next_feynman_prerequisites": [wp for wp in eval_result.get("weak_points", [])[:3]],
            }

        return {
            "item_scores":   eval_result.get("item_scores", []),
            "final_score":   eval_result["final_score"],
            "mastery_level": eval_result["mastery_level"],
            "strong_points": eval_result["strong_points"],
            "weak_points":   eval_result["weak_points"],
            "final_summary": eval_result["final_summary"],
            "passed":        passed,
            "pass_score":    pass_score,
            "new_status":    new_status,
            "correction_plan": correction_plan,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"complete_feynman({session_id}) Unhandled error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Internal error: {e}")


@app.post("/api/sessions/{session_id}/complete", dependencies=[Depends(_require_admin)])
async def complete_session(session_id: int):
    """用户手动结束（不进费曼）"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # Phase 5: state transition guard
    st = session.get("status", "")
    if st not in ("learning", "deepening", "revising"):
        raise HTTPException(409, f"Cannot complete in status '{st}'. Allowed: learning, deepening, revising.")

    db.update_session(session_id, status="completed")

    # 自动创建复习排期（如果有分数）
    db.schedule_review(session_id, session.get("score"))

    return {"ok": True}


@app.post("/api/sessions/{session_id}/reopen", dependencies=[Depends(_require_admin)])
async def reopen_session(session_id: int):
    """费曼检验未通过，回到深化阶段"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # Phase 5: state transition guard
    st = session.get("status", "")
    if st not in ("completed", "revising"):
        raise HTTPException(409, f"Cannot reopen in status '{st}'. Allowed: completed, revising.")

    db.update_session(session_id, status="deepening")
    return {"ok": True}


# ── Gaps API ──────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/gaps", dependencies=[Depends(_require_admin)])
async def get_session_gaps(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {"session_id": session_id, "gaps": db.get_unresolved_gaps(session_id)}


# ── Knowledge Node API ───────────────────────────────────

class KnowledgeNodeUpdate(BaseModel):
    knowledge_node_id: str | None = None


@app.patch("/api/sessions/{session_id}/knowledge-node", dependencies=[Depends(_require_admin)])
async def update_knowledge_node(session_id: int, body: KnowledgeNodeUpdate):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    db.set_knowledge_node(session_id, body.knowledge_node_id)
    return {"ok": True, "knowledge_node_id": body.knowledge_node_id}


@app.post("/api/sessions/{session_id}/suggest-knowledge-nodes", dependencies=[Depends(_require_admin)])
async def suggest_nodes_for_session(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    query = (session.get("title") or "") + " " + (session.get("content") or "")
    tree = db.get_knowledge_tree()
    suggestions = db.suggest_knowledge_nodes(tree, query)
    return {"session_id": session_id, "suggestions": suggestions, "current_node_id": db.get_knowledge_node(session_id)}


@app.get("/api/knowledge-tree/progress", dependencies=[Depends(_require_admin)])
async def get_tree_progress():
    """知识树进度：每个节点的 session 统计"""
    progress = db.get_knowledge_tree_progress()
    # 注入节点标题
    tree = db.get_knowledge_tree()
    for p in progress:
        node = db.find_node_by_id(tree, p["node_id"])
        p["title"] = node["title"] if node else p["node_id"]
    return {"progress": progress}


# ── Phase 4: DB-backed Job Worker ──────────────────────────

_WORKER_SLEEP = 2  # seconds between polls
_JOB_SEMAPHORE = asyncio.Semaphore(3)  # Phase 5: max concurrent AI jobs

async def _job_worker():
    """Background worker: polls the jobs table and processes pending jobs."""
    print("[Worker] Job worker started (max concurrency: 3)")
    while True:
        try:
            job = db.claim_pending_job()
            if job:
                asyncio.create_task(_process_job_with_sem(job))
        except Exception as e:
            print(f"[Worker] Poll error: {e}")
        await asyncio.sleep(_WORKER_SLEEP)


async def _process_job_with_sem(job: dict):
    """Process a job with concurrency limit."""
    async with _JOB_SEMAPHORE:
        await _process_job(job)


async def _process_job(job: dict):
    """Process a single job by job_type."""
    job_id = job["id"]
    job_type = job.get("job_type", "")
    try:
        if job_type == "generate_session_answer":
            await _process_generate_session_answer(job_id, job)
        elif job_type == "generate_inbox_questions":
            await _process_generate_inbox_questions(job_id, job)
        else:
            db.fail_job(job_id, f"Unknown job_type: {job_type}", rescind=True)
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        db.fail_job(job_id, err_msg)


async def _process_generate_session_answer(job_id: int, job: dict):
    """Process a 'generate_session_answer' job: generate title + answer for a new session."""
    payload = db._jload(job.get("payload")) if job.get("payload") else {}
    sid = payload.get("session_id")
    if not sid:
        return db.fail_job(job_id, "Missing session_id in payload", rescind=True)

    session = db.get_session(sid)
    if not session:
        # Session was deleted — discard the job
        return db.complete_job(job_id, {"discarded": True, "reason": "session deleted"})

    # If session is already in a later state (e.g., manually fixed), skip
    if session.get("status") not in ("preparing", "error"):
        return db.complete_job(job_id, {"skipped": True, "reason": f"session already {session.get('status')}"})

    content = payload.get("content", session.get("content", ""))
    stype = payload.get("type", session.get("type", "question"))
    web_search = payload.get("web_search", False)
    node_id = payload.get("knowledge_node_id")

    # 如果有知识节点，获取节点上下文
    knowledge_node = None
    if node_id:
        tree = db.get_knowledge_tree()
        knowledge_node = db.find_node_by_id(tree, node_id)

    # 并行生成标题和回答
    title, result = await asyncio.gather(
        ai.generate_title(content),
        ai.generate_initial_answer(content, "", stype,
                                   web_search=web_search,
                                   knowledge_node=knowledge_node),
    )
    answer = result["answer"]
    db.update_session(sid, title=title, material=answer, error_msg=None, status="learning")
    db.complete_job(job_id, {"title": title, "answer_len": len(answer)})


async def _process_generate_inbox_questions(job_id: int, job: dict):
    """Process a 'generate_inbox_questions' job: turn inbox content into candidate questions."""
    payload = db._jload(job.get("payload")) if job.get("payload") else {}
    item_id = payload.get("inbox_item_id")
    if not item_id:
        return db.fail_job(job_id, "Missing inbox_item_id in payload", rescind=True)

    item = db.get_inbox_item(item_id)
    if not item:
        return db.complete_job(job_id, {"discarded": True, "reason": "inbox item deleted"})
    if item.get("status") == "archived":
        return db.complete_job(job_id, {"skipped": True, "reason": "inbox item archived"})

    content = payload.get("content") or item.get("content", "")
    direction = payload.get("direction")
    replace = bool(payload.get("replace", True))
    db.update_inbox_item(item_id, status="generating", error_msg=None)
    try:
        result = await ai.generate_inbox_questions(content, direction=direction)
        questions = result.get("questions") if isinstance(result, dict) else []
        if not isinstance(questions, list) or not questions:
            raise RuntimeError("AI did not generate valid inbox questions")
        ids = db.create_inbox_questions(item_id, questions[:5], replace_candidates=replace)
        db.update_inbox_item(item_id, status="ready", error_msg=None)
        db.complete_job(job_id, {"inbox_item_id": item_id, "question_count": len(ids)})
    except Exception as e:
        db.update_inbox_item(item_id, status="error", error_msg=str(e)[:500])
        raise


# ── Maintenance ────────────────────────────────────────────

@app.get("/api/knowledge-tree/sessions", dependencies=[Depends(_require_admin)])
async def get_sessions_for_node(node_id: str, limit: int = 50):
    """获取某个知识节点的所有 session"""
    sessions = db.get_sessions_by_node(node_id, limit)
    # 注入节点标题
    tree = db.get_knowledge_tree()
    node = db.find_node_by_id(tree, node_id)
    node_title = node["title"] if node else node_id
    return {"node_id": node_id, "node_title": node_title, "sessions": sessions, "count": len(sessions)}


@app.get("/api/knowledge-tree/mastery", dependencies=[Depends(_require_admin)])
async def get_knowledge_mastery():
    """Phase 5: 知识树掌握度模型 — 每个节点的 mastery 评分、状态、gaps、复习"""
    mastery = db.get_knowledge_tree_mastery()
    return {"tree": mastery}


@app.get("/api/knowledge-tree/recommend", dependencies=[Depends(_require_admin)])
async def get_recommended():
    """Phase 5: 智能推荐 — 下一步该学什么节点"""
    nodes = db.get_recommended_nodes(3)
    return {"recommended": nodes}


# ── Maintenance ────────────────────────────────────────────

async def _retry_preparing_session(session_id: int):
    """Retry the background AI generation for a stale preparing session."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.get("status") != "preparing" and session.get("status") != "error":
        raise HTTPException(400, f"Session is {session.get('status')}, not preparing/error")
    
    content = session.get("content", "")
    session_type = session.get("type", "question")
    
    db.update_session(session_id, status="preparing", error_msg=None)
    
    try:
        # Parallel title + answer generation
        title, result = await asyncio.gather(
            ai.generate_title(content),
            ai.generate_initial_answer(content, "", session_type),
        )
        db.update_session(session_id, title=title, material=result["answer"], status="learning")
    except Exception as e:
        db.update_session(session_id, status="error", error_msg=str(e))
        raise
    
    return {"ok": True, "session_id": session_id, "status": "learning"}


@app.get("/api/maintenance/stale-preparing", dependencies=[Depends(_require_admin)])
async def list_stale_preparing(timeout_minutes: int = 5):
    """List sessions stuck in preparing state."""
    return db.get_stale_preparing_sessions(timeout_minutes)


@app.post("/api/maintenance/retry-preparing/{session_id}", dependencies=[Depends(_require_admin)])
async def retry_preparing(session_id: int):
    """Retry a stale preparing session via job queue."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.get("status") not in ("preparing", "error"):
        raise HTTPException(400, f"Session is {session.get('status')}, not preparing/error")

    db.update_session(session_id, status="preparing", error_msg=None)
    db.create_job(
        "generate_session_answer",
        {"session_id": session_id, "content": session.get("content", ""),
         "type": session.get("type", "question"), "web_search": session.get("web_search", False),
         "knowledge_node_id": session.get("knowledge_node_id")},
    )
    return {"ok": True, "session_id": session_id, "status": "preparing"}


@app.post("/api/maintenance/recover-all-stale", dependencies=[Depends(_require_admin)])
async def recover_all_stale(timeout_minutes: int = 5):
    """Mark all stale preparing sessions as error."""
    db.mark_stale_preparing_as_error(timeout_minutes)
    return db.get_stale_preparing_sessions(timeout_minutes)


@app.get("/api/jobs/status", dependencies=[Depends(_require_admin)])
async def jobs_status():
    """Job queue status (Phase 4)."""
    return {
        "pending": db.get_pending_job_count(),
        "running": db.get_running_job_count(),
    }


# ── Review Schedule APIs ──────────────────────────────────────────────────

class ReviewCompleteRequest(BaseModel):
    score: int | None = None  # 可选，用于排期下一轮复习


@app.get("/api/review/today", dependencies=[Depends(_require_admin)])
async def get_today_reviews():
    """今日到期 + overdue 的复习任务列表。"""
    reviews = db.get_today_reviews(50)
    return {"reviews": reviews, "count": len(reviews)}


@app.post("/api/review/{review_id}/complete", dependencies=[Depends(_require_admin)])
async def complete_review(review_id: int, body: ReviewCompleteRequest = ReviewCompleteRequest()):
    """标记一次复习完成，自动排期下一轮（艾宾浩斯曲线）。"""
    db.mark_review_complete(review_id, body.score)
    return {"ok": True}


@app.post("/api/review/{review_id}/skip", dependencies=[Depends(_require_admin)])
async def skip_review(review_id: int):
    """跳过本次复习，状态标记为 'skipped'（不算完成，下一轮按原间隔提前）。"""
    if not db.skip_review(review_id):
        raise HTTPException(404, "Review schedule not found")
    return {"ok": True, "status": "skipped"}


class ReviewSubmitRequest(BaseModel):
    content: str  # 用户重新解释的内容


@app.post("/api/review/{review_id}/submit", dependencies=[Depends(_require_admin)])
async def submit_review(review_id: int, body: ReviewSubmitRequest):
    """Phase 4.2: 提交复习内容（重新解释），AI 评估后完成复习。"""
    # 获取复习记录
    from sqlalchemy import text as sa_text
    row = None
    with db.get_engine().connect() as conn:
        r = conn.execute(
            sa_text("SELECT * FROM review_schedule WHERE id = :rid"),
            {"rid": review_id}
        ).mappings().fetchone()
        if r:
            row = dict(r)

    if not row:
        raise HTTPException(404, "Review not found")
    if row.get("status") != "pending":
        raise HTTPException(400, f"Review is {row.get('status')}, not pending")

    session_id = row["session_id"]
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # 调用 AI 评估重新解释
    original_question = session.get("content") or session.get("title", "")
    ai_material = session.get("material", "")

    result = await ai.evaluate_review_re_explanation(
        original_question, ai_material, body.content
    )

    # 格式化 AI 反馈
    feedback_lines = []
    if result.get("verdict"):
        feedback_lines.append(f"**评价**: {result['verdict']}")
    if result.get("praise"):
        feedback_lines.append(f"\n**亮点**: {result['praise']}")
    if result.get("gap"):
        feedback_lines.append(f"\n**待加强**: {result['gap']}")
    feedback = "\n".join(feedback_lines)

    score = result.get("score", 50)
    db.submit_review_content(review_id, body.content, feedback, score)

    return {
        "ok": True,
        "score": score,
        "feedback": feedback,
        "passed": score >= 60,
    }


@app.get("/api/command-center", dependencies=[Depends(_require_admin)])
async def command_center():
    """聚合仪表盘：待办费曼 + 今日复习 + 失败项 + 学习中 + 推荐节点。"""
    return db.get_command_center_data()


# ── Phase 4.2: Rubric Management ─────────────────────────────

@app.get("/api/rubrics", dependencies=[Depends(_require_admin)])
async def list_rubrics():
    """列出所有评分标准及其版本信息。"""
    settings = db.get_settings()
    rubrics = settings.get("rubrics", {})
    version = settings.get("rubric_version", 1)
    return {
        "rubrics": rubrics,
        "version": version,
    }


class RubricUpdateRequest(BaseModel):
    role: str
    system_prompt: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v):
        allowed = {"review_explain", "feynman", "deepen_evaluate"}
        if v not in allowed:
            raise ValueError(f"Unknown role: {v}. Allowed: {sorted(allowed)}")
        return v


@app.patch("/api/rubrics", dependencies=[Depends(_require_admin)])
async def update_rubric(body: RubricUpdateRequest):
    """更新某个 role 的评分标准，自动递增版本号。"""
    result = db.upsert_rubric(body.role, body.system_prompt)
    return {
        "ok": True,
        "role": body.role,
        "version": result["version"],
    }


# ── Maintenance: Invariant Checks ──────────────────────────────

@app.get("/api/maintenance/check-invariants", dependencies=[Depends(_require_admin)])
async def check_invariants(stale_minutes: int = 10):
    """检查状态机一致性。"""
    return db.check_invariants(stale_minutes)


@app.post("/api/maintenance/repair-invariants", dependencies=[Depends(_require_admin)])
async def repair_invariants(dry_run: bool = True):
    """修复常见的状态机不一致。dry_run=true 只预览不执行。"""
    return db.repair_invariants(dry_run=dry_run)


# ── Phase 4.3: Weekly Report ─────────────────────────────────

@app.get("/api/report/weekly", dependencies=[Depends(_require_admin)])
async def weekly_report():
    """生成本周学习周报（Markdown 格式）。"""
    data = db.get_weekly_report_data()

    # 构建 Markdown 报告
    from datetime import datetime
    lines = []
    lines.append(f"# 📊 学习周报")
    lines.append(f"**{data['week_start']}** ~ **{data['week_end']}**")
    lines.append("")

    # 1. 概览
    lines.append("## 📈 本周概览")
    lines.append("")
    lines.append(f"- 新建会话：**{data['sessions_created']}** 个")
    lines.append(f"- 完成学习：**{data['sessions_completed']}** 个")
    lines.append("")

    # 2. 复习统计
    lines.append("## 🔁 间隔复习")
    lines.append("")
    lines.append(f"- 完成复习：**{data['reviews_completed']}** 次")
    if data['review_avg_score'] is not None:
        avg = data['review_avg_score']
        emoji = "🟢" if avg >= 80 else ("🟡" if avg >= 60 else "🔴")
        lines.append(f"- 复习均分：{emoji} **{avg}**")
    lines.append(f"- 待复习：**{data['reviews_pending']}** 项")
    lines.append("")

    # 3. 薄弱点
    lines.append("## 🎯 薄弱环节")
    lines.append("")
    lines.append(f"- 未解决的薄弱点：**{data['open_gaps']}** 个")
    lines.append("")

    # 4. 本周完成的 session
    if data['recent_done']:
        lines.append("## ✅ 本周完成")
        lines.append("")
        for s in data['recent_done']:
            score_str = f" ({s.get('score', '?')}/5)" if s.get('score') is not None else ""
            lines.append(f"- [{s['title']}{score_str}](/#session/{s['id']})")
        lines.append("")

    # 5. 推荐
    if data['recommended']:
        lines.append("## 🚀 下周建议")
        lines.append("")
        for i, node in enumerate(data['recommended'][:3], 1):
            title = node.get("title", node.get("id", "?"))
            reason = node.get("reason", "")
            lines.append(f"{i}. **{title}** — {reason}")
        lines.append("")

    lines.append("---")
    lines.append(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    report_md = "\n".join(lines)

    return {
        "data": data,
        "markdown": report_md,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7070, reload=False)
