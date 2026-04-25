import unittest

from learn_flow import build_command_center


class BuildCommandCenterTests(unittest.TestCase):
    def test_prioritizes_pending_followup_from_latest_session(self):
        profile = {
            "current_task": {"id": 7, "title": "当前任务", "prompt": "解释缓存命中"},
            "current_task_id": 7,
        }
        sessions = [
            {
                "id": 11,
                "domain_id": "cs",
                "title": "缓存命中机制",
                "ai_feedback": "主线是对的，但例子不够具体。",
                "ai_questions": '["什么叫命中？", "举一个具体例子。"]',
                "user_responses": None,
                "quality_score": 3,
                "status": "evaluated",
                "created_at": "2026-04-14T12:00:00",
            }
        ]

        state = build_command_center(profile, sessions, [])

        self.assertEqual(state["next_step"]["kind"], "answer_followup")
        self.assertTrue(state["latest_feedback"]["pending_followup"])
        self.assertEqual(state["latest_feedback"]["pending_followup_count"], 2)
        self.assertEqual(state["latest_feedback"]["questions"], ["什么叫命中？", "举一个具体例子。"])

    def test_resumes_current_task_when_no_pending_followup(self):
        profile = {
            "current_task": {"id": 3, "title": "写一段清晰摘要", "prompt": "围绕一个概念写摘要"},
            "current_task_id": 3,
        }
        sessions = [
            {
                "id": 9,
                "domain_id": "write",
                "title": "旧会话",
                "ai_feedback": "表达还可以。",
                "ai_questions": "[]",
                "user_responses": "[]",
                "quality_score": 4,
                "status": "completed",
                "created_at": "2026-04-13T12:00:00",
            }
        ]

        state = build_command_center(profile, sessions, [])

        self.assertEqual(state["next_step"]["kind"], "resume_current_task")
        self.assertIn("写一段清晰摘要", state["next_step"]["title"])

    def test_points_to_due_concept_when_no_current_task(self):
        profile = {"current_task": None, "current_task_id": None}
        due_concepts = [
            {
                "id": 5,
                "domain_id": "psych",
                "term": "确认偏误",
                "next_review_date": "2026-04-14",
            }
        ]

        state = build_command_center(profile, [], due_concepts)

        self.assertEqual(state["next_step"]["kind"], "review_due_concept")
        self.assertEqual(state["due_concepts_count"], 1)
        self.assertIn("确认偏误", state["next_step"]["title"])

    def test_falls_back_to_pick_recommendation(self):
        profile = {"current_task": None, "current_task_id": None}

        state = build_command_center(profile, [], [])

        self.assertEqual(state["next_step"]["kind"], "pick_recommendation")
        self.assertIsNone(state["latest_feedback"])
        self.assertEqual(state["due_concepts_count"], 0)

    def test_latest_feedback_keeps_completed_summary_without_pending_followup(self):
        profile = {"current_task": None, "current_task_id": None}
        sessions = [
            {
                "id": 12,
                "domain_id": "phil",
                "title": "知识与信念",
                "ai_feedback": "论证骨架已经出来了，可以继续打磨概念边界。",
                "ai_questions": '["知识和真信念有什么差别？"]',
                "user_responses": '["知识要求理由充分，真信念不一定。"]',
                "quality_score": 4,
                "status": "completed",
                "created_at": "2026-04-14T13:00:00",
            }
        ]

        state = build_command_center(profile, sessions, [])

        self.assertFalse(state["latest_feedback"]["pending_followup"])
        self.assertEqual(state["latest_feedback"]["score"], 4)
        self.assertEqual(state["next_step"]["kind"], "pick_recommendation")


if __name__ == "__main__":
    unittest.main()
