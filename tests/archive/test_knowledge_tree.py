import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


class KnowledgeTreeTests(unittest.TestCase):
    def _iter_leaves(self, nodes):
        for node in nodes or []:
            children = node.get("children") or []
            if children:
                yield from self._iter_leaves(children)
            else:
                yield node

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.hermes_home = Path(self.tmpdir.name) / ".hermes"
        (self.hermes_home / "workspace" / "learn-system").mkdir(parents=True, exist_ok=True)

        self.original_env = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.hermes_home)

        self.repo_root = Path(__file__).resolve().parents[1]
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))

        for name in ["learn_db", "learn_server"]:
            if name in sys.modules:
                del sys.modules[name]

        self.learn_db = importlib.import_module("learn_db")
        self.learn_db.init_db()

    def tearDown(self):
        for name in ["learn_server", "learn_db"]:
            if name in sys.modules:
                del sys.modules[name]
        if self.original_env is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self.original_env
        self.tmpdir.cleanup()

    def test_profile_roundtrip_selected_knowledge_nodes(self):
        profile = self.learn_db.upsert_profile(
            selected_knowledge_nodes=[
                "cs.system.os.scheduler",
                "write.argument.counter.counterexample",
            ]
        )
        self.assertEqual(
            profile["selected_knowledge_nodes"],
            [
                "cs.system.os.scheduler",
                "write.argument.counter.counterexample",
            ],
        )
        loaded = self.learn_db.get_profile()
        self.assertEqual(
            loaded["selected_knowledge_nodes"],
            [
                "cs.system.os.scheduler",
                "write.argument.counter.counterexample",
            ],
        )

    def test_profile_roundtrip_current_task_knowledge_binding(self):
        profile = self.learn_db.upsert_profile(
            current_task_knowledge_node_id="cs.system.os.scheduler",
            current_task_knowledge_path_text="计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )
        self.assertEqual(profile["current_task_knowledge_node_id"], "cs.system.os.scheduler")
        self.assertEqual(
            profile["current_task_knowledge_path_text"],
            "计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )
        loaded = self.learn_db.get_profile()
        self.assertEqual(loaded["current_task_knowledge_node_id"], "cs.system.os.scheduler")
        self.assertEqual(
            loaded["current_task_knowledge_path_text"],
            "计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )

    def test_profile_read_sanitizes_legacy_selected_knowledge_nodes(self):
        conn = self.learn_db.get_conn()
        conn.execute(
            "UPDATE profile_settings SET selected_knowledge_nodes=? WHERE id=?",
            (
                '["cs.os.process", "cs.system", "cs.system.os.scheduler", "cs.system.os.scheduler"]',
                self.learn_db.PROFILE_ID,
            ),
        )
        conn.commit()
        conn.close()

        loaded = self.learn_db.get_profile()
        self.assertEqual(loaded["selected_knowledge_nodes"], ["cs.system.os.scheduler"])

    def test_profile_roundtrip_manual_knowledge_focus(self):
        profile = self.learn_db.upsert_profile(
            manual_knowledge_node_id="cs.system.os.scheduler",
            manual_knowledge_path_text="计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )
        self.assertEqual(profile["manual_knowledge_node_id"], "cs.system.os.scheduler")
        self.assertEqual(
            profile["manual_knowledge_path_text"],
            "计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )
        loaded = self.learn_db.get_profile()
        self.assertEqual(loaded["manual_knowledge_node_id"], "cs.system.os.scheduler")
        self.assertEqual(
            loaded["manual_knowledge_path_text"],
            "计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )

    def test_get_knowledge_tree_returns_four_domains(self):
        tree = self.learn_db.get_knowledge_tree()
        self.assertEqual(len(tree), 4)
        ids = {item["id"] for item in tree}
        self.assertEqual(ids, {"cs", "write", "psych", "phil"})
        cs = next(item for item in tree if item["id"] == "cs")
        self.assertTrue(cs["children"])
        self.assertIn("系统与并发", {child["title"] for child in cs["children"]})

    def test_knowledge_tree_expands_into_richer_four_level_domains(self):
        tree = self.learn_db.get_knowledge_tree()
        leaves = list(self._iter_leaves(tree))
        self.assertGreaterEqual(len(leaves), 140)

        cs = next(item for item in tree if item["id"] == "cs")
        branch_titles = {child["title"] for child in cs["children"]}
        self.assertIn("AI 系统", branch_titles)
        self.assertIn("工程与交付", branch_titles)

        language = next(child for child in cs["children"] if child["id"] == "cs.lang")
        self.assertIn("编译器与解释器", {child["title"] for child in language["children"]})
        compiler_branch = next(child for child in language["children"] if child["id"] == "cs.lang.compiler")
        self.assertIn("解析与 AST", {child["title"] for child in compiler_branch["children"]})

        systems = next(child for child in cs["children"] if child["id"] == "cs.system")
        self.assertIn("操作系统", {child["title"] for child in systems["children"]})
        self.assertIn("安全与身份", {child["title"] for child in systems["children"]})

        os_branch = next(child for child in systems["children"] if child["id"] == "cs.system.os")
        self.assertIn("调度与并发", {child["title"] for child in os_branch["children"]})

        scheduler_leaf = next(child for child in os_branch["children"] if child["id"] == "cs.system.os.scheduler" )
        self.assertIn("上下文切换", scheduler_leaf.get("keywords", []))
        self.assertTrue(scheduler_leaf.get("prompt_fragments"))

        ai_branch = next(child for child in cs["children"] if child["id"] == "cs.ai")
        self.assertIn("多模态与语音", {child["title"] for child in ai_branch["children"]})

        write = next(item for item in tree if item["id"] == "write")
        self.assertIn("研究与素材", {child["title"] for child in write["children"]})

        psych = next(item for item in tree if item["id"] == "psych")
        bias_branch = next(child for child in psych["children"] if child["id"] == "psych.cognition")
        bias_subbranch = next(child for child in bias_branch["children"] if child["id"] == "psych.cognition.bias")
        self.assertIn("可得性偏差", {child["title"] for child in bias_subbranch["children"]})

        phil = next(item for item in tree if item["id"] == "phil")
        ethics = next(child for child in phil["children"] if child["id"] == "phil.ethics")
        applied = next(child for child in ethics["children"] if child["id"] == "phil.ethics.applied")
        self.assertIn("AI 治理与隐私", {child["title"] for child in applied["children"]})

    def test_frontend_knowledge_tree_uses_row_layout(self):
        import re

        html = (self.repo_root / "index.html").read_text(encoding="utf-8")
        css = (self.repo_root / "assets" / "app.css").read_text(encoding="utf-8")
        self.assertIn("kt-leaf-grid", html)
        self.assertIn("knowledge-leaf-keywords", html)
        self.assertIn("knowledge-domain-meta", html)
        self.assertRegex(css, r"\.kt-branch-grid\s*\{[^}]*grid-template-columns:\s*1fr;")
        self.assertRegex(css, r"\.kt-leaf-grid\s*\{[^}]*grid-template-columns:\s*1fr;")
        self.assertIn(".knowledge-leaf", css)
        self.assertIn(".knowledge-leaf-keywords", css)
        self.assertIn(".knowledge-domain-meta", css)

    def test_frontend_knowledge_tree_sort_keeps_stable_order_with_selected_state(self):
        html = (self.repo_root / "index.html").read_text(encoding="utf-8")
        self.assertIn("const originalIndex = items.indexOf(a) - items.indexOf(b);", html)
        self.assertIn("const sortLeaves = (items) => [...items].sort((a, b) => {", html)
        self.assertIn("return originalIndex;", html)
        self.assertIn("const statusOrder = hasProgress && avgScore > 0 && avgScore < 3.5 ? 0 : 1;", html)
        self.assertNotIn("isSelected ? 0 : 1", html)

    def test_frontend_knowledge_tree_explains_auto_save_and_manual_focus(self):
        html = (self.repo_root / "index.html").read_text(encoding="utf-8")
        self.assertIn("选择后会自动保存", html)
        self.assertIn("当前聚焦知识节点", html)
        self.assertIn("暂存一个当前最想围绕它学习/输出的节点", html)
        self.assertNotIn("保存方向选择", html)
        self.assertNotIn("当前绑定知识节点", html)
        self.assertNotIn("设为当前绑定", html)

    def test_frontend_knowledge_tree_clear_actions_also_autosave(self):
        import re

        html = (self.repo_root / "index.html").read_text(encoding="utf-8")
        self.assertIn("async function persistSelectedKnowledgeNodes", html)
        self.assertRegex(html, r"await persistSelectedKnowledgeNodes\(\[\]\);")
        self.assertRegex(
            html,
            r"await persistSelectedKnowledgeNodes\(\(state\.selectedKnowledgeNodes \|\| \[\]\)\.filter\(\(id\) => !id\.startsWith\(prefix\)\)\);",
        )
        self.assertNotIn("state.selectedKnowledgeNodes = [];\n        renderKnowledgeTree();", html)

    def test_recommendations_prioritize_selected_knowledge_nodes(self):
        self.learn_db.upsert_profile(
            preferred_domains=["cs"],
            selected_knowledge_nodes=["cs.system.os.scheduler"],
            daily_minutes_goal=25,
        )
        recs = self.learn_db.build_recommendation_candidates(limit=8)
        self.assertTrue(recs)
        self.assertTrue(any(item.get("knowledge_node_id") == "cs.system.os.scheduler" for item in recs))
        self.assertTrue(all(item["domain_id"] == "cs" for item in recs[:3]))
        target = next(item for item in recs if item.get("knowledge_node_id") == "cs.system.os.scheduler")
        self.assertIn("操作系统", target.get("knowledge_path_text", ""))
        self.assertIn("调度与并发", target.get("knowledge_path_text", ""))

    def test_recommendations_no_longer_use_broad_template_source(self):
        self.learn_db.upsert_profile(
            preferred_domains=["cs"],
            selected_knowledge_nodes=[],
            daily_minutes_goal=25,
        )
        recs = self.learn_db.build_recommendation_candidates(limit=8)
        self.assertTrue(recs)
        self.assertTrue(all(item.get("source") != "template" for item in recs))
        self.assertTrue(any(item.get("source") == "knowledge" for item in recs))

    def test_api_returns_knowledge_tree_and_selected_nodes(self):
        self.learn_db.upsert_profile(selected_knowledge_nodes=["phil.mind.consciousness.qualia"])
        learn_server = importlib.import_module("learn_server")

        data = asyncio.run(learn_server.get_knowledge_tree())
        self.assertIn("tree", data)
        self.assertEqual(data["selected_nodes"], ["phil.mind.consciousness.qualia"])
        self.assertEqual(len(data["tree"]), 4)

    def test_api_returns_sanitized_selected_nodes_for_legacy_profile(self):
        conn = self.learn_db.get_conn()
        conn.execute(
            "UPDATE profile_settings SET selected_knowledge_nodes=? WHERE id=?",
            (
                '["cs.os.process", "cs.system", "cs.system.os.scheduler"]',
                self.learn_db.PROFILE_ID,
            ),
        )
        conn.commit()
        conn.close()

        learn_server = importlib.import_module("learn_server")
        data = asyncio.run(learn_server.get_knowledge_tree())

        self.assertEqual(data["selected_nodes"], ["cs.system.os.scheduler"])

    def test_api_can_update_selected_nodes(self):
        learn_server = importlib.import_module("learn_server")

        body = learn_server.KnowledgeSelectionUpdate(
            selected_nodes=["psych.self.identity.narrative", "write.argument.counter.counterexample"]
        )
        data = asyncio.run(learn_server.update_knowledge_selection(body))
        self.assertEqual(
            data["selected_knowledge_nodes"],
            ["psych.self.identity.narrative", "write.argument.counter.counterexample"],
        )

    def test_api_profile_can_update_manual_knowledge_focus(self):
        learn_server = importlib.import_module("learn_server")

        body = learn_server.ProfileUpdate(
            manual_knowledge_node_id="cs.system.os.scheduler",
            manual_knowledge_path_text="计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )
        data = asyncio.run(learn_server.update_profile(body))
        self.assertEqual(data["manual_knowledge_node_id"], "cs.system.os.scheduler")
        self.assertEqual(
            data["manual_knowledge_path_text"],
            "计算机 / 系统与并发 / 操作系统 / 调度与并发",
        )

    def test_session_can_bind_to_knowledge_node(self):
        sid = self.learn_db.create_session(
            domain_id="cs",
            session_type="feynman",
            title="解释上下文切换",
            content="上下文切换会保存和恢复线程现场...",
            duration=25,
            knowledge_node_id="cs.system.os.scheduler",
        )
        session = self.learn_db.get_session(sid)
        self.assertEqual(session["knowledge_node_id"], "cs.system.os.scheduler")

    def test_knowledge_progress_stats_aggregate_bound_sessions(self):
        sid1 = self.learn_db.create_session(
            domain_id="cs",
            session_type="feynman",
            title="解释上下文切换",
            content="第一次",
            duration=20,
            knowledge_node_id="cs.system.os.scheduler",
        )
        self.learn_db.update_session(sid1, status="submitted")
        sid2 = self.learn_db.create_session(
            domain_id="cs",
            session_type="feynman",
            title="再次解释上下文切换",
            content="第二次",
            duration=30,
            knowledge_node_id="cs.system.os.scheduler",
        )
        self.learn_db.update_session(sid2, quality_score=4, status="completed")
        stats = self.learn_db.get_knowledge_progress()
        node = stats["cs.system.os.scheduler"]
        self.assertEqual(node["session_count"], 2)
        self.assertEqual(node["total_minutes"], 50)
        self.assertEqual(node["avg_score"], 4.0)
        self.assertEqual(node["knowledge_path_text"], "计算机 / 系统与并发 / 操作系统 / 调度与并发")


if __name__ == "__main__":
    unittest.main()
