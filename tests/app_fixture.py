"""Reusable isolated AIIterate app fixture for repeatable tests.

The production service uses PostgreSQL and real LLM calls. These helpers run the
same FastAPI endpoints against a temporary SQLite database with deterministic AI
stubs, so the suite is cheap, isolated, and safe to repeat.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Iterable

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOKEN = "test-admin-token"
AUTH_HEADERS = {"X-Admin-Token": TOKEN}


def setup_isolated_app(tmp_path, monkeypatch, review_scores: Iterable[int] = (86,)):
    """Return (client, db, server) wired to a temp SQLite DB and fake AI."""
    import aiterate_db as db
    import aiterate_server as server

    cfg = {"type": "sqlite", "sqlite_path": str(tmp_path / "aiterate-test.db")}
    monkeypatch.setattr(db, "load_db_config", lambda: cfg)
    db.init_db()
    db.upsert_profile(settings__admin_token=TOKEN, settings__feynman_pass_score=60)
    server._active_sessions.clear()

    scores = list(review_scores) or [86]

    async def fake_generate_title(content: str):
        return "测试主题：" + content[:18]

    async def fake_generate_initial_answer(title: str, content: str = "", type: str = "question", **kwargs):
        question = title if not content else content
        return {"answer": f"这是针对「{question}」的结构化回答。它包含背景、核心概念、例子和边界条件，用于全流程测试。" * 2}

    async def fake_evaluate_user_take(original_question: str, ai_answer: str, user_take: str):
        gaps = [] if "完整" in user_take or "核心" in user_take else ["需要补充关键边界"]
        return {
            "score": 82 if not gaps else 55,
            "understood_well": not gaps,
            "praise": "抓住了主干。",
            "gaps": gaps,
            "verdict": "理解基本准确。" if not gaps else "还需要补足边界条件。",
        }

    async def fake_suggest_deepen_prompts(original_question: str, gaps: list[str]):
        return {"suggestions": [f"如何理解：{g}" for g in gaps]}

    async def fake_answer_followup_question(original_question: str, ai_answer: str, press_input: str, history=None, **kwargs):
        return {"answer": f"追问「{press_input}」的回答：先澄清概念，再给出工程例子，最后说明常见误区。"}

    async def fake_generate_review_questions(original_question: str, ai_material: str, learning_history: str, **kwargs):
        return {"questions": ["请用自己的话解释核心概念。", "请给出一个反例或边界情况。"]}

    async def fake_evaluate_review_answers(original_question: str, questions: list[str], answers: list[str], **kwargs):
        score = scores.pop(0) if scores else 86
        return {
            "item_scores": [
                {"question": q, "score": score, "comment": "回答覆盖了要点。" if score >= 60 else "回答过于粗略。"}
                for q in questions
            ],
            "final_score": score,
            "mastery_level": "掌握" if score >= 60 else "待加强",
            "strong_points": ["能复述主干"] if score >= 60 else [],
            "weak_points": [] if score >= 60 else ["边界情况", "具体例子"],
            "final_summary": "费曼检验通过。" if score >= 60 else "需要回到深化阶段补足薄弱点。",
        }

    async def fake_evaluate_review_re_explanation(original_question: str, ai_material: str, user_content: str):
        return {"score": 88, "praise": "复习有效。", "feedback": "解释清楚。"}

    monkeypatch.setattr(server.ai, "generate_title", fake_generate_title)
    monkeypatch.setattr(server.ai, "generate_initial_answer", fake_generate_initial_answer)
    monkeypatch.setattr(server.ai, "evaluate_user_take", fake_evaluate_user_take)
    monkeypatch.setattr(server.ai, "suggest_deepen_prompts", fake_suggest_deepen_prompts)
    monkeypatch.setattr(server.ai, "answer_followup_question", fake_answer_followup_question)
    monkeypatch.setattr(server.ai, "generate_review_questions", fake_generate_review_questions)
    monkeypatch.setattr(server.ai, "evaluate_review_answers", fake_evaluate_review_answers)
    monkeypatch.setattr(server.ai, "evaluate_review_re_explanation", fake_evaluate_review_re_explanation)

    return TestClient(server.app), db, server


def run_next_answer_job(db, server):
    """Synchronously process the next queued session-answer job."""
    job = db.claim_pending_job()
    assert job is not None, "expected a pending generate_session_answer job"
    asyncio.run(server._process_generate_session_answer(job["id"], job))
    return job


def create_learning_session(client, db, server, content="什么是幂等性？") -> int:
    r = client.post(
        "/api/sessions",
        headers=AUTH_HEADERS,
        json={"content": content, "type": "question", "web_search": False},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    run_next_answer_job(db, server)
    s = client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS)
    assert s.status_code == 200, s.text
    assert s.json()["status"] == "learning"
    return sid
