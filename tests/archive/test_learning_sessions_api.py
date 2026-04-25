import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks


class LearningSessionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.hermes_home = Path(self.tmpdir.name) / ".hermes"
        (self.hermes_home / "workspace" / "learn-system").mkdir(parents=True, exist_ok=True)

        self.original_env = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.hermes_home)

        self.repo_root = Path(__file__).resolve().parents[1]
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))

        for name in ["learn_db", "learn_ai", "learn_server"]:
            if name in sys.modules:
                del sys.modules[name]

        self.learn_db = importlib.import_module("learn_db")
        self.learn_server = importlib.import_module("learn_server")
        self.learn_db.init_db()

    def tearDown(self):
        for name in ["learn_server", "learn_ai", "learn_db"]:
            if name in sys.modules:
                del sys.modules[name]
        if self.original_env is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self.original_env
        self.tmpdir.cleanup()

    def test_create_session_defers_initial_answer_to_background_task(self):
        background = BackgroundTasks()
        body = self.learn_server.SessionCreate(title="什么是缓存一致性", content="", type="question")

        with patch.object(
            self.learn_server.ai,
            "generate_initial_answer",
            new=AsyncMock(return_value={"answer": "缓存一致性是多副本下保持数据视图一致。"}),
        ):
            result = asyncio.run(self.learn_server.create_session_and_answer(body, background))
            session_id = result["session_id"]

            created = self.learn_db.get_session(session_id)
            self.assertEqual(result["status"], "processing")
            self.assertEqual(created["status"], "processing")
            self.assertEqual(self.learn_db.get_session_rounds(session_id), [])

            asyncio.run(background())

        completed = self.learn_db.get_session(session_id)
        rounds = self.learn_db.get_session_rounds(session_id)
        self.assertEqual(completed["status"], "answered")
        self.assertEqual(completed["ai_feedback"], "缓存一致性是多副本下保持数据视图一致。")
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["round_type"], "initial_answer")
        self.assertEqual(rounds[0]["status"], "read")

    def test_initial_answer_failure_is_persisted_on_session(self):
        background = BackgroundTasks()
        body = self.learn_server.SessionCreate(title="失败问题", content="", type="question")

        with patch.object(
            self.learn_server.ai,
            "generate_initial_answer",
            new=AsyncMock(side_effect=RuntimeError("Missing DEEPSEEK_API_KEY in ~/.hermes/.env")),
        ):
            result = asyncio.run(self.learn_server.create_session_and_answer(body, background))
            session_id = result["session_id"]
            asyncio.run(background())

        failed = self.learn_db.get_session(session_id)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Missing DEEPSEEK_API_KEY", failed["error_message"])
        self.assertEqual(self.learn_db.get_session_rounds(session_id), [])

    def test_workspace_endpoint_returns_pending_review_round(self):
        session_id = self.learn_db.create_session(
            domain_id="general",
            session_type="question",
            title="解释 CAP 定理",
            content="",
            duration=0,
        )
        self.learn_db.update_session(session_id, ai_feedback="初始回答", status="reviewing")

        initial_round = self.learn_db.create_session_round(
            session_id=session_id,
            round_number=1,
            ai_feedback="初始回答",
            ai_questions=[],
            round_score=0,
        )
        self.learn_db.update_session_round(initial_round, round_type="initial_answer", status="read")

        review_round = self.learn_db.create_session_round(
            session_id=session_id,
            round_number=2,
            ai_feedback="",
            ai_questions=["CAP 三者分别是什么？", "为什么不能同时满足？"],
            round_score=0,
        )
        self.learn_db.update_session_round(review_round, round_type="review_qa", status="pending")

        payload = asyncio.run(self.learn_server.get_session_workspace(session_id))

        self.assertEqual(payload["phase"], "reviewing")
        self.assertEqual(payload["session"]["status"], "reviewing")
        self.assertEqual(payload["current_review_round"]["id"], review_round)
        self.assertEqual(payload["current_review_round"]["ai_questions"], ["CAP 三者分别是什么？", "为什么不能同时满足？"])

    def test_complete_review_returns_to_deepening_when_not_passed(self):
        session_id = self.learn_db.create_session(
            domain_id="general",
            session_type="question",
            title="解释 MVCC",
            content="",
            duration=0,
        )
        self.learn_db.update_session(session_id, ai_feedback="初始回答", status="reviewing")

        initial_round = self.learn_db.create_session_round(
            session_id=session_id,
            round_number=1,
            ai_feedback="初始回答",
            ai_questions=[],
            round_score=0,
        )
        self.learn_db.update_session_round(initial_round, round_type="initial_answer", status="read")

        review_round = self.learn_db.create_session_round(
            session_id=session_id,
            round_number=2,
            ai_feedback="",
            ai_questions=["快照读是什么？", "当前读是什么？"],
            round_score=0,
        )
        self.learn_db.update_session_round(review_round, round_type="review_qa", status="pending")

        request = self.learn_server.ReviewAnswerRequest(
            round_id=review_round,
            answers=["是某种读取", "是另一种读取"],
        )

        with patch.object(
            self.learn_server.ai,
            "evaluate_review_answers",
            new=AsyncMock(
                return_value={
                    "final_score": 3,
                    "mastery_level": "继续深化",
                    "strong_points": ["知道有两种读取"],
                    "weak_points": ["没有解释版本链和可见性判断"],
                    "final_summary": "理解还不够扎实，回到深化阶段继续迭代。",
                }
            ),
        ):
            result = asyncio.run(self.learn_server.complete_review(session_id, request))

        refreshed = self.learn_db.get_session(session_id)
        review_rows = self.learn_db.get_session_rounds(session_id)
        review = next(r for r in review_rows if r["id"] == review_round)

        self.assertFalse(result["passed"])
        self.assertEqual(result["new_status"], "iterating")
        self.assertEqual(refreshed["status"], "iterating")
        self.assertEqual(review["user_responses"], ["是某种读取", "是另一种读取"])
        self.assertEqual(review["round_score"], 3)

    def test_frontend_contains_sidebar_and_workspace_loader(self):
        html = (self.repo_root / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="sessionSidebar"', html)
        self.assertIn("async function refreshSessionList()", html)
        self.assertIn("async function loadSessionWorkspace(sessionId", html)
        self.assertIn("setSelectedSession(null)", html)
        self.assertIn("pollWorkspaceUntilReady", html)


if __name__ == "__main__":
    unittest.main()
