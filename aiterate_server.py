"""
AIIterate FastAPI Backend
Port: 7070
"""
import asyncio
import json
from pathlib import Path
from typing import Annotated, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import sys
sys.path.insert(0, str(Path(__file__).parent))
import aiterate_db as db
import aiterate_ai as ai

FRONTEND = Path(__file__).parent / "index.html"
ASSETS_DIR = Path(__file__).parent / "assets"

app = FastAPI(title="AIIterate API", version="3.0.0")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


# ── Admin Token ────────────────────────────────────────────

async def _require_admin(x_admin_token: Annotated[str | None, Header()] = None):
    if not db.check_admin_token(x_admin_token):
        raise HTTPException(401, "Missing or invalid admin token")
    return True


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

    payload = {
        "session": session,
        "rounds": rounds,
        "phase": phase,
        "current_review_group":  current_review_group,
        "latest_review_result":  latest_review_result,
        "take_evaluations":      take_rounds_with_eval,
        "unresolved_gaps":       gaps,
        "review_report":         review_report,
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
    # 自动恢复重启时丢失的 preparing 任务（> 2 分钟 stale 才标 error）
    try:
        stale = db.get_stale_preparing_sessions(timeout_minutes=2)
        if stale["count"] > 0:
            db.mark_stale_preparing_as_error(timeout_minutes=2)
            print(f"[AIIterate] Marked {stale['count']} stale preparing sessions as error")
    except Exception as e:
        print(f"[AIIterate] Stale check failed (non-fatal): {e}")
    print("[AIIterate] DB ready")


@app.get("/")
async def serve_frontend():
    token = db.get_or_create_admin_token()
    html = FRONTEND.read_text(encoding="utf-8")
    html = html.replace(
        '<script type="module" src="/assets/js/app.js"></script>',
        '<script>window.AITERATE_TOKEN="' + token + '";</script>\n  <script type="module" src="/assets/js/app.js"></script>',
    )
    return HTMLResponse(content=html)


# ── Profile ───────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    theme: Optional[str] = None  # "night" | "mono"


_LLM_ROLES = ["title", "answer", "evaluate", "review", "deepen"]


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
    # 先用候选配置测试连接，成功再落盘
    test_result = db.test_db_config(updates)
    if not test_result["ok"]:
        raise HTTPException(400, f"DB 连接测试失败：{test_result['error']}")
    db.save_db_config(updates)
    db.init_engine()
    return {"ok": True}


@app.get("/api/knowledge-tree")
async def get_knowledge_tree():
    return {"tree": db.get_knowledge_tree()}


@app.get("/api/profile")
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

    if kwargs:
        db.upsert_profile(**kwargs)
    return await get_settings()


@app.get("/api/ready")
async def get_ready():
    """返回当前配置是否就绪（LLM、Tavily）"""
    settings = db.get_settings()
    llm_ok    = bool((settings.get("llm") or {}).get("api_key", ""))
    tavily_ok = bool(settings.get("tavily_api_key", ""))
    return {"llm": llm_ok, "tavily": tavily_ok}


# ── Stats ─────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    return db.get_stats()


# ── Sessions ──────────────────────────────────────────────

@app.get("/api/sessions")
async def get_sessions(limit: int = 20):
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


@app.post("/api/sessions", dependencies=[Depends(_require_admin)])
async def create_session_and_answer(body: SessionCreate, background_tasks: BackgroundTasks):
    """阶段1：创建 session，后台异步AI生成标题+初始回答"""
    # 先用 content 前 40 字作为临时标题，AI 生成正式标题后更新
    temp_title = body.content[:40].strip()
    sid = db.create_session(
        title=temp_title,
        content=body.content,
        type=body.type,
    )
    db.update_session(sid, status="preparing")

    # 如果有知识节点，立即绑定
    knowledge_node = None
    if body.knowledge_node_id:
        db.set_knowledge_node(sid, body.knowledge_node_id)
        tree = db.get_knowledge_tree()
        knowledge_node = db.find_node_by_id(tree, body.knowledge_node_id)

    async def generate_answer():
        try:
            # 并行生成标题和回答
            title_task = ai.generate_title(body.content)
            answer_task = ai.generate_initial_answer(
                body.content, "", body.type,
                web_search=body.web_search,
                knowledge_node=knowledge_node,
            )
            title, result = await asyncio.gather(title_task, answer_task)
            answer = result["answer"]
            db.update_session(sid, title=title, material=answer, error_msg=None, status="learning")
        except Exception as exc:
            db.update_session(sid, status="error", error_msg=str(exc))

    background_tasks.add_task(generate_answer)

    return {
        "session_id": sid,
        "status": "preparing",
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: int):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s


@app.get("/api/sessions/{session_id}/rounds")
async def get_rounds(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    rounds = db.get_rounds(session_id)
    return {"session_id": session_id, "rounds": rounds}


@app.get("/api/sessions/{session_id}/workspace")
async def get_session_workspace(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    rounds = db.get_rounds(session_id)
    return _build_session_workspace_payload(session, rounds)


class DeepenRequest(BaseModel):
    action_type: str  # "take" 或 "press"
    content: str      # take: 用户的理解文本; press: 用户的追问文本

    @field_validator("action_type")
    @classmethod
    def action_type_valid(cls, v):
        if v not in ("take", "press"):
            raise ValueError('action_type 必须是 take 或 press')
        return v

    @field_validator("content")
    @classmethod
    def content_valid(cls, v):
        if not v or not v.strip():
            raise ValueError("内容不能为空")
        if len(v) > 10000:
            raise ValueError(f"内容过长（{len(v)} 字符），最多 10000 字符")
        return v.strip()


@app.post("/api/sessions/{session_id}/deepen", dependencies=[Depends(_require_admin)])
async def deepen(session_id: int, body: DeepenRequest):
    """深化阶段：take(理解) 或 press(追问)"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

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
        }
        rid = db.create_round_with_seq(
            session_id=session_id, type="take",
            input=body.content, output=eval_result["verdict"],
            score=eval_result["score"], status="evaluated",
            eval_json=eval_json,
        )
        db.update_session(session_id, status="deepening")

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
        answer_result = await ai.answer_followup_question(original_question, ai_answer, body.content, history)
        rid = db.create_round_with_seq(
            session_id=session_id, type="press",
            input=body.content, output=answer_result["answer"],
            score=None, status="deepening",
        )
        db.update_session(session_id, status="deepening")
        return {
            "round_id": rid,
            "type": "press",
            "answer": answer_result["answer"],
        }

    else:
        raise HTTPException(400, "action_type must be 'take' or 'press'")


@app.post("/api/sessions/{session_id}/start-feynman", dependencies=[Depends(_require_admin)])
async def start_feynman(session_id: int):
    """费曼阶段：AI生成检验题，每题一条 round"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    rounds = db.get_rounds(session_id)
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
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    rounds = db.get_rounds(session_id)
    feynman_rounds = sorted(
        [r for r in rounds if r.get("group_id") == body.group_id],
        key=lambda r: r["seq"]
    )
    if not feynman_rounds:
        raise HTTPException(404, "Feynman group not found")

    questions = [r["input"] for r in feynman_rounds]
    eval_result = await ai.evaluate_review_answers(session["title"], questions, body.answers)
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
    }
    db.save_review_report(session_id, report)

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
    }


@app.post("/api/sessions/{session_id}/complete", dependencies=[Depends(_require_admin)])
async def complete_session(session_id: int):
    """用户手动结束（不进费曼）"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    db.update_session(session_id, status="completed")
    return {"ok": True}


@app.post("/api/sessions/{session_id}/reopen", dependencies=[Depends(_require_admin)])
async def reopen_session(session_id: int):
    """费曼检验未通过，回到深化阶段"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    db.update_session(session_id, status="deepening")
    return {"ok": True}


# ── Gaps API ──────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/gaps")
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


@app.post("/api/sessions/{session_id}/suggest-knowledge-nodes")
async def suggest_nodes_for_session(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    query = (session.get("title") or "") + " " + (session.get("content") or "")
    tree = db.get_knowledge_tree()
    suggestions = db.suggest_knowledge_nodes(tree, query)
    return {"session_id": session_id, "suggestions": suggestions, "current_node_id": db.get_knowledge_node(session_id)}


@app.get("/api/knowledge-tree/progress")
async def get_tree_progress():
    """知识树进度：每个节点的 session 统计"""
    progress = db.get_knowledge_tree_progress()
    # 注入节点标题
    tree = db.get_knowledge_tree()
    for p in progress:
        node = db.find_node_by_id(tree, p["node_id"])
        p["title"] = node["title"] if node else p["node_id"]
    return {"progress": progress}


@app.get("/api/knowledge-tree/sessions")
async def get_sessions_for_node(node_id: str, limit: int = 50):
    """获取某个知识节点的所有 session"""
    sessions = db.get_sessions_by_node(node_id, limit)
    # 注入节点标题
    tree = db.get_knowledge_tree()
    node = db.find_node_by_id(tree, node_id)
    node_title = node["title"] if node else node_id
    return {"node_id": node_id, "node_title": node_title, "sessions": sessions, "count": len(sessions)}


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
        title, material = await asyncio.gather(
            ai.generate_title(content),
            ai.generate_initial_answer(content, "", session_type),
        )
        db.update_session(session_id, title=title, material=material, status="learning")
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
    """Retry a stale preparing session from the question content."""
    from fastapi import BackgroundTasks
    return await _retry_preparing_session(session_id)


@app.post("/api/maintenance/recover-all-stale", dependencies=[Depends(_require_admin)])
async def recover_all_stale(timeout_minutes: int = 5):
    """Mark all stale preparing sessions as error."""
    db.mark_stale_preparing_as_error(timeout_minutes)
    return db.get_stale_preparing_sessions(timeout_minutes)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7070, reload=False)
