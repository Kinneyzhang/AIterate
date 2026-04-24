"""
AIIterate FastAPI Backend
Port: 7070
"""
import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent))
import aiterate_db as db
import aiterate_ai as ai

FRONTEND = Path(__file__).parent / "index.html"
ASSETS_DIR = Path(__file__).parent / "assets"

app = FastAPI(title="AIIterate API", version="3.0.0")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


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
        "db_path": f"postgresql:{db.PG_DBNAME}",
        "version": "3.0.0",
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _session_phase(status: str | None) -> str:
    return {
        "preparing": "preparing",
        "learning":  "learning",
        "deepening": "deepening",
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

    return {
        "session": session,
        "rounds": rounds,
        "phase": phase,
        "current_review_group":  current_review_group,
        "latest_review_result":  latest_review_result,
    }


@app.on_event("startup")
async def startup():
    db.init_db()
    print("[AIIterate] DB ready")


@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND))


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
    llm:            Optional[LLMConfig] = None
    tavily_api_key: Optional[str]       = None


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

@app.get("/api/db-config")
async def get_db_config():
    cfg = db.load_db_config()
    safe = dict(cfg)
    if safe.get("password"):
        safe["password"] = "••••••"
    return safe

@app.put("/api/db-config")
async def update_db_config(body: DbConfigUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "no fields to update")
    db.save_db_config(updates)
    try:
        db.init_engine()
    except Exception as e:
        raise HTTPException(500, f"DB 连接失败：{e}")
    return {"ok": True}


@app.get("/api/knowledge-tree")
async def get_knowledge_tree():
    return {"tree": db.get_knowledge_tree()}


@app.get("/api/profile")
async def get_profile():
    p = db.get_profile()
    return {"id": p["id"], "theme": p["theme"], "updated_at": p.get("updated_at")}


@app.patch("/api/profile")
async def update_profile(body: ProfileUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "theme" in updates and updates["theme"] not in {"night", "mono"}:
        raise HTTPException(400, "theme must be night or mono")
    return db.upsert_profile(**updates)


# ── Settings ──────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    settings = db.get_settings()
    llm = settings.get("llm") or {}
    roles_raw = llm.get("roles") or {}
    roles = {role: roles_raw.get(role, {}) for role in _LLM_ROLES}
    return {
        "llm": {
            "provider": llm.get("provider", ""),
            "base_url":  llm.get("base_url",  ""),
            "api_key":   llm.get("api_key",   ""),
            "model":     llm.get("model",     ""),
            "roles":     roles,
        },
        "tavily_api_key": settings.get("tavily_api_key", ""),
    }


@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return await get_settings()
    kwargs = {}
    if "llm" in updates:
        # 深度合并 settings.llm
        kwargs["settings__llm"] = updates["llm"]
    if "tavily_api_key" in updates:
        kwargs["settings__tavily_api_key"] = updates["tavily_api_key"]
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


@app.post("/api/sessions")
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

    async def generate_answer():
        try:
            # 并行生成标题和回答
            title_task = ai.generate_title(body.content)
            answer_task = ai.generate_initial_answer(body.content, "", body.type, web_search=body.web_search)
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


@app.post("/api/sessions/{session_id}/deepen")
async def deepen(session_id: int, body: DeepenRequest):
    """深化阶段：take(理解) 或 press(追问)"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    original_question = session["title"]
    ai_answer = session.get("material", "")
    rounds = db.get_rounds(session_id)
    seq = db.next_seq(session_id)

    if body.action_type == "take":
        eval_result = await ai.evaluate_user_take(original_question, ai_answer, body.content)
        rid = db.create_round(
            session_id=session_id, seq=seq, type="take",
            input=body.content, output=eval_result["verdict"],
            score=eval_result["score"], status="evaluated",
        )
        db.update_session(session_id, status="deepening")
        return {
            "round_id": rid,
            "type": "take",
            "score": eval_result["score"],
            "praise": eval_result["praise"],
            "gaps": eval_result["gaps"],
            "verdict": eval_result["verdict"],
            "understood_well": eval_result["understood_well"],
        }

    elif body.action_type == "press":
        history = [
            {"question": r.get("input", ""), "answer": r.get("output", "")}
            for r in rounds if r.get("type") == "press"
        ]
        answer_result = await ai.answer_followup_question(original_question, ai_answer, body.content, history)
        rid = db.create_round(
            session_id=session_id, seq=seq, type="press",
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


@app.post("/api/sessions/{session_id}/start-feynman")
async def start_feynman(session_id: int):
    """费曼阶段：AI生成检验题，每题一条 round"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    rounds = db.get_rounds(session_id)
    learning_history = " | ".join([r.get("output", "")[:100] for r in rounds])

    result = await ai.generate_review_questions(
        session["title"], session.get("material", ""), learning_history,
    )
    questions = result["questions"]
    seq_start = db.next_seq(session_id)

    # 每题建一条 round，group_id = 第一题的 round id
    round_ids = []
    first_id = None
    for i, q in enumerate(questions):
        rid = db.create_round(
            session_id=session_id, seq=seq_start + i, type="feynman",
            input=q, output=None, score=None, status="pending",
        )
        if first_id is None:
            first_id = rid
        round_ids.append(rid)

    # 用第一题 id 作为 group_id，标记这批题属于同一轮费曼
    for rid in round_ids:
        db.update_round(rid, group_id=first_id)

    db.update_session(session_id, status="feynman")
    return {"group_id": first_id, "round_ids": round_ids, "questions": questions}


class FeynmanAnswerRequest(BaseModel):
    group_id: int
    answers: list[str]   # 按 round 顺序对应


@app.post("/api/sessions/{session_id}/complete-feynman")
async def complete_feynman(session_id: int, body: FeynmanAnswerRequest):
    """费曼阶段：提交作答，逐题更新 round，AI整体评估"""
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
    passed = eval_result["final_score"] >= 60

    # 逐题写回 output / score / score_comment
    item_scores = eval_result.get("item_scores", [])
    for i, r in enumerate(feynman_rounds):
        ev = item_scores[i] if i < len(item_scores) else {}
        db.update_round(
            r["id"],
            output=body.answers[i] if i < len(body.answers) else "",
            score=ev.get("score"),
            score_comment=ev.get("comment", ""),
            status="completed",
        )

    new_status = "completed" if passed else "revising"
    db.update_session(session_id, score=eval_result["final_score"], status=new_status)

    return {
        "item_scores":   item_scores,
        "final_score":   eval_result["final_score"],
        "mastery_level": eval_result["mastery_level"],
        "strong_points": eval_result["strong_points"],
        "weak_points":   eval_result["weak_points"],
        "final_summary": eval_result["final_summary"],
        "passed":        passed,
        "new_status":    new_status,
    }


@app.post("/api/sessions/{session_id}/complete")
async def complete_session(session_id: int):
    """用户手动结束（不进费曼）"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    db.update_session(session_id, status="completed")
    return {"ok": True}


@app.post("/api/sessions/{session_id}/reopen")
async def reopen_session(session_id: int):
    """费曼检验未通过，回到深化阶段"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    db.update_session(session_id, status="deepening")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7070, reload=False)
