import json
from typing import Any
import aiterate_db as db


def _get_domain_names() -> dict:
    return {}  # domains 已移除，不再使用领域分类


def _json_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _latest_feedback(sessions: list[dict]) -> dict | None:
    if not sessions:
        return None
    latest = sessions[0]

    # 兼容新旧两种模式
    # 新模式：status=iterating，通过 rounds 表判断
    # 旧模式：status=evaluated，通过 ai_questions 判断
    status = latest.get("status", "")
    pending_followup = status == "deepening"

    questions = [str(x).strip() for x in _json_list(latest.get("input")) if str(x).strip()]
    responses = [str(x).strip() for x in _json_list(latest.get("output")) if str(x).strip()]

    # 兼容旧的 evaluated 状态
    if not pending_followup and status == "evaluated":
        pending_followup = bool(questions) and not responses

    return {
        "session_id": latest.get("id"),
        "title": latest.get("title") or "未命名输出",
        "domain_id": latest.get("domain_id"),
        "domain_name": _get_domain_names().get(latest.get("domain_id"), latest.get("domain_id") or "未知领域"),
        "score": latest.get("score") or 0,
        "summary": latest.get("material") or "暂无评估摘要。",
        "status": status,
        "created_at": latest.get("created_at"),
        "questions": questions,
        "pending_followup": pending_followup,
        "pending_followup_count": len(questions) if pending_followup else 0,
        "has_responses": bool(responses),
    }


def _next_step(profile: dict, latest_feedback: dict | None, due_concepts: list[dict]) -> dict:
    current_task = (profile or {}).get("current_task") or None
    if latest_feedback and latest_feedback.get("pending_followup"):
        return {
            "kind": "answer_followup",
            "title": f"先回答追问：{latest_feedback['title']}",
            "description": f"上次输出后还有 {latest_feedback['pending_followup_count']} 个追问没回答，先把这一轮闭环收完。",
            "cta": "回答追问",
        }
    if current_task:
        return {
            "kind": "resume_current_task",
            "title": f"继续当前任务：{current_task.get('title') or '未命名任务'}",
            "description": "你已经选了任务，最值钱的下一步不是换题，而是直接输出自己的理解。",
            "cta": "带入提交区",
        }
    if due_concepts:
        concept = due_concepts[0]
        return {
            "kind": "review_due_concept",
            "title": f"先复习概念：{concept.get('term') or '未命名概念'}",
            "description": "有到期概念卡片，先做一次短复盘，比继续堆新输入更划算。",
            "cta": "复盘概念",
        }
    return {
        "kind": "pick_recommendation",
        "title": "先选一个推荐任务",
        "description": "你还没有当前任务。先接受一个推荐卡片，再开始学习闭环。",
        "cta": "去选任务",
    }


def build_command_center(profile: dict | None, sessions: list[dict] | None, due_concepts: list[dict] | None) -> dict:
    profile = profile or {}
    sessions = sessions or []
    due_concepts = due_concepts or []
    latest_feedback = _latest_feedback(sessions)
    next_step = _next_step(profile, latest_feedback, due_concepts)
    return {
        "current_task": profile.get("current_task"),
        "latest_feedback": latest_feedback,
        "due_concepts_count": len(due_concepts),
        "next_step": next_step,
    }
