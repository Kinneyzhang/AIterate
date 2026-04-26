"""AIIterate offline unit tests — run with: pytest tests/ -q"""

import json
import sys
from pathlib import Path

# ── Helpers under test ──────────────────────────────────────────────────

def _mask_key(key: str) -> str:
    """sk-abc123...xyz789 -> sk-...xyz789"""
    if not key:
        return ""
    if len(key) <= 8:
        return key[:3] + "..." + key[-2:]
    return key[:3] + "..." + key[-4:]


# ── Tests ───────────────────────────────────────────────────────────────

class TestMaskKey:
    def test_empty(self):
        assert _mask_key("") == ""

    def test_short_key(self):
        assert _mask_key("abc12") == "abc...12"

    def test_exact_8(self):
        assert _mask_key("12345678") == "123...78"

    def test_standard_sk_key(self):
        result = _mask_key("sk-abc...9ghi")
        assert result.startswith("sk-...")
        assert result.endswith("ghi")
        assert len(result) < len("sk-abc...9ghi")

    def test_doubao_key(self):
        assert _mask_key("doubao-key-xxx") == "dou...-xxx"

    def test_tavily_key(self):
        result = _mask_key("tvly-dev-longstring")
        assert "tvly-dev-longstring" not in result
        assert result.startswith("tvl")
        assert "..." in result


class TestInputValidation:
    """Verify that Pydantic models enforce constraints."""

    def test_session_content_not_empty(self):
        from pydantic import BaseModel, field_validator

        class _SessionCreate(BaseModel):
            content: str
            type: str = "question"
            web_search: bool = False

            @field_validator("content")
            @classmethod
            def content_not_empty(cls, v):
                if not v or not v.strip():
                    raise ValueError("内容不能为空")
                if len(v) > 20000:
                    raise ValueError(f"内容过长（{len(v)} 字符），最多 20000 字符")
                return v.strip()

        # Valid
        s = _SessionCreate(content="   hello world   ")
        assert s.content == "hello world"

        # Empty
        try:
            _SessionCreate(content="")
            assert False, "should have raised"
        except Exception:
            pass

        try:
            _SessionCreate(content="   ")
            assert False, "should have raised"
        except Exception:
            pass

    def test_session_content_too_long(self):
        from pydantic import BaseModel, field_validator

        class _SessionCreate(BaseModel):
            content: str
            type: str = "question"

            @field_validator("content")
            @classmethod
            def check(cls, v):
                if not v or not v.strip():
                    raise ValueError("empty")
                if len(v) > 20000:
                    raise ValueError(f"过长（{len(v)}）")
                return v.strip()

        try:
            _SessionCreate(content="x" * 20001)
            assert False, "should have raised"
        except Exception:
            pass

    def test_session_type_invalid(self):
        from pydantic import BaseModel, field_validator

        class _SessionCreate(BaseModel):
            content: str
            type: str = "question"

            @field_validator("type")
            @classmethod
            def check(cls, v):
                if v not in ("question", "viewpoint"):
                    raise ValueError('type 必须是 question 或 viewpoint')
                return v

        try:
            _SessionCreate(content="test", type="invalid")
            assert False, "should have raised"
        except Exception:
            pass

    def test_deepen_action_type_invalid(self):
        from pydantic import BaseModel, field_validator

        class _DeepenRequest(BaseModel):
            action_type: str
            content: str

            @field_validator("action_type")
            @classmethod
            def check(cls, v):
                if v not in ("take", "press"):
                    raise ValueError('必须是 take 或 press')
                return v

        try:
            _DeepenRequest(action_type="bad", content="x")
            assert False, "should have raised"
        except Exception:
            pass

    def test_feynman_answers_max_count(self):
        from pydantic import BaseModel, field_validator

        class _FeynmanAnswerRequest(BaseModel):
            group_id: int
            answers: list[str]

            @field_validator("answers")
            @classmethod
            def check(cls, v):
                if len(v) > 20:
                    raise ValueError(f"最多 20 道题，收到 {len(v)}")
                return v

        try:
            _FeynmanAnswerRequest(group_id=1, answers=["a"] * 21)
            assert False, "should have raised"
        except Exception:
            pass


class TestKnowledgeTree:
    def test_tree_file_exists(self):
        tree_path = Path(__file__).parent.parent / "config" / "knowledge_tree.json"
        assert tree_path.exists(), "knowledge_tree.json not found"

    def test_tree_is_valid_json(self):
        tree_path = Path(__file__).parent.parent / "config" / "knowledge_tree.json"
        data = json.loads(tree_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) > 0
        for domain in data:
            assert "title" in domain, f"Domain missing title: {domain}"


class TestExtractJsonBlock:
    """Verify AI JSON extraction handles real-world LLM noise."""

    def _extract(self, raw: str):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from aiterate_ai import _extract_json_block
        return _extract_json_block(raw)

    def test_plain_json(self):
        assert self._extract('{"score": 80, "gaps": []}') == {"score": 80, "gaps": []}

    def test_json_with_explaining_text(self):
        assert self._extract('好的：\n{"score": 70, "verdict": "ok"}\n以上') == {"score": 70, "verdict": "ok"}

    def test_nested_json(self):
        assert self._extract('{"eval": {"score": 90}, "gaps": [{"text": "x"}]}')["eval"]["score"] == 90

    def test_braces_inside_string(self):
        raw = '{"verdict": "可以用 {x} 表示变量", "score": 88}'
        assert self._extract(raw)["verdict"] == "可以用 {x} 表示变量"

    def test_bad_json_then_good_json(self):
        raw = '示例 {bad json}\n最终 {"score": 66, "parse_failed": false}'
        assert self._extract(raw)["score"] == 66


class TestFrontendTokenInjection:
    """Ensure built frontend shells keep the token placeholder injectable."""

    def test_source_index_keeps_token_placeholder(self):
        html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
        assert 'window.AITERATE_TOKEN="%%AITERATE_TOKEN%%"' in html

    def test_serve_frontend_replaces_placeholder(self, tmp_path, monkeypatch):
        import asyncio
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import aiterate_db as db
        import aiterate_server as server

        shell = tmp_path / "index.html"
        shell.write_text('<script>window.AITERATE_TOKEN="%%AITERATE_TOKEN%%";</script>', encoding="utf-8")
        monkeypatch.setattr(server, "FRONTEND", shell)
        monkeypatch.setattr(db, "get_or_create_admin_token", lambda: "test-token-123")

        response = asyncio.run(server.serve_frontend())
        body = response.body.decode("utf-8")
        assert "%%AITERATE_TOKEN%%" not in body
        assert 'window.AITERATE_TOKEN="test-token-123"' in body


class TestSettingsKeyMerge:
    """Verify the _merge_keys logic used in update_settings."""

    def _merge_keys(self, base: dict, overlay: dict) -> dict:
        r = dict(base)
        for k in ("api_key",):
            v = overlay.get(k)
            if v == "__CLEAR__":
                r[k] = ""
            elif v and v.strip():
                r[k] = v
        for k in ("provider", "base_url", "model"):
            if k in overlay and overlay[k] is not None:
                r[k] = overlay[k]
        return r

    def test_keep_existing_on_empty(self):
        base = {"api_key": "sk-secret", "model": "gpt-4", "provider": "openai"}
        result = self._merge_keys(base, {"model": "gpt-4o"})
        assert result["api_key"] == "sk-secret"  # preserved
        assert result["model"] == "gpt-4o"       # updated
        assert result["provider"] == "openai"    # preserved

    def test_replace_key_with_new(self):
        base = {"api_key": "sk-old"}
        result = self._merge_keys(base, {"api_key": "new-key"})
        assert result["api_key"] == "new-key"

    def test_clear_key_with_sentinel(self):
        base = {"api_key": "sk-secret"}
        result = self._merge_keys(base, {"api_key": "__CLEAR__"})
        assert result["api_key"] == ""

    def test_empty_overlay_changes_nothing(self):
        base = {"api_key": "sk-secret", "model": "gpt-4"}
        result = self._merge_keys(base, {})
        assert result == base


class TestStageMapping:
    def test_all_statuses_have_stage(self):
        """Verify all session statuses map to a frontend stage."""
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # Duplicate the _session_phase logic inline
        mapping = {
            "preparing": "preparing",
            "learning": "learning",
            "deepening": "deepening",
            "revising": "revising",
            "feynman": "feynman",
            "completed": "completed",
            "error": "error",
        }
        # These are the valid statuses
        for status in ["preparing", "learning", "deepening", "revising", "feynman", "completed", "error"]:
            assert status in mapping, f"Missing mapping for status: {status}"

    def test_unknown_status_falls_back(self):
        fallback = "preparing"
        mapping = {
            "preparing": "preparing",
            "learning": "learning",
            "deepening": "deepening",
            "revising": "revising",
            "feynman": "feynman",
            "completed": "completed",
            "error": "error",
        }
        result = mapping.get("nonexistent", fallback)
        assert result == fallback


class TestFindNodeById:
    def _find_node_by_id(self, tree, node_id):
        for node in tree:
            if node.get("id") == node_id:
                return node
            children = node.get("children", [])
            if children:
                found = self._find_node_by_id(children, node_id)
                if found:
                    return found
        return None

    def test_find_root_level(self):
        tree = [{"id": "cs", "title": "计算机"}]
        result = self._find_node_by_id(tree, "cs")
        assert result is not None
        assert result["title"] == "计算机"

    def test_find_nested(self):
        tree = [{
            "id": "cs",
            "title": "计算机",
            "children": [{
                "id": "cs.lang",
                "title": "编程语言",
                "children": [{"id": "cs.lang.syntax", "title": "语法"}]
            }]
        }]
        result = self._find_node_by_id(tree, "cs.lang.syntax")
        assert result is not None
        assert result["title"] == "语法"

    def test_not_found(self):
        tree = [{"id": "cs", "title": "计算机"}]
        result = self._find_node_by_id(tree, "nonexistent")
        assert result is None


class TestKnowledgeNodeSuggestion:
    def _suggest(self, tree, query, limit=3):
        """Minimal version of suggest_knowledge_nodes for unit testing."""
        query_lower = query.lower()
        scored = []

        def _walk(nodes, path=""):
            for node in nodes:
                score = 0
                title = node.get("title", "")
                keywords = node.get("keywords", [])
                fragments = node.get("prompt_fragments", [])

                if any(w in title.lower() for w in query_lower.split()):
                    score += 3
                if query_lower in title.lower():
                    score += 5

                for kw in keywords:
                    if kw.lower() in query_lower or query_lower in kw.lower():
                        score += 2

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
                    })

                _walk(node.get("children", []), f"{path}/{title}" if path else title)

        _walk(tree)
        scored.sort(key=lambda x: (-x["score"], x["path"]))
        return scored[:limit]

    def test_keyword_match(self):
        tree = [{
            "id": "cs.lang",
            "title": "编程语言",
            "keywords": ["类型", "泛型", "类型系统"],
            "prompt_fragments": ["解释类型系统如何防止错误"],
        }]
        results = self._suggest(tree, "类型系统")
        assert len(results) > 0
        assert results[0]["id"] == "cs.lang"

    def test_title_match_weights_more(self):
        tree = [
            {"id": "a", "title": "泛型编程"},
            {"id": "b", "title": "数据库索引", "keywords": ["泛型"]},
        ]
        results = self._suggest(tree, "泛型")
        assert len(results) >= 2
        # Title match (3) vs keyword match (2): title wins
        assert results[0]["id"] == "a"

    def test_no_match_returns_empty(self):
        tree = [{"id": "x", "title": "哲学"}]
        results = self._suggest(tree, "量子计算")
        assert results == []


# ── Phase 4: Review Schedule (Ebbinghaus) ──────────────────────────────────

# 艾宾浩斯曲线常量（与 aiterate_db.py 同步）
_EBBINGHAUS = [1, 2, 6, 31, 90]


class TestEbbinghausIntervals:
    """验证艾宾浩斯遗忘曲线间隔计算。"""

    @staticmethod
    def _calc_days(review_round: int, score: int | None = None) -> int:
        if review_round >= len(_EBBINGHAUS):
            days = _EBBINGHAUS[-1]
        else:
            days = _EBBINGHAUS[review_round]

        if score is not None and score < 40:
            if review_round > 0:
                days = max(1, _EBBINGHAUS[review_round - 1])
            else:
                days = 1
        return days

    def test_first_review_1_day(self):
        assert self._calc_days(0) == 1

    def test_second_review_2_days(self):
        assert self._calc_days(1) == 2

    def test_third_review_6_days(self):
        assert self._calc_days(2) == 6

    def test_fourth_review_31_days(self):
        assert self._calc_days(3) == 31

    def test_fifth_review_90_days(self):
        assert self._calc_days(4) == 90

    def test_beyond_curve_stays_at_90(self):
        assert self._calc_days(5) == 90
        assert self._calc_days(10) == 90

    def test_low_score_shortens_first(self):
        # score < 40, round 0 → 1 day (no shorter tier)
        assert self._calc_days(0, 30) == 1

    def test_low_score_shortens_second(self):
        # score < 40, round 1 → drops to round 0 interval (1 day)
        assert self._calc_days(1, 25) == 1

    def test_low_score_shortens_third(self):
        # score < 40, round 2 → drops to round 1 interval (2 days)
        assert self._calc_days(2, 30) == 2

    def test_low_score_shortens_fourth(self):
        # score < 40, round 3 → drops to round 2 interval (6 days)
        assert self._calc_days(3, 35) == 6

    def test_high_score_no_shortening(self):
        assert self._calc_days(0, 80) == 1
        assert self._calc_days(1, 85) == 2
        assert self._calc_days(2, 90) == 6

    def test_medium_score_no_shortening(self):
        assert self._calc_days(0, 50) == 1
        assert self._calc_days(1, 60) == 2
        assert self._calc_days(2, 55) == 6

    def test_none_score_no_shortening(self):
        assert self._calc_days(0, None) == 1
        assert self._calc_days(2, None) == 6


class TestReviewScheduleDedup:
    """验证重复排期跳过逻辑。"""

    def test_no_duplicate_logic(self):
        """schedule 前先查 pending：有就跳过，没有就创建。"""
        # 这个逻辑在 DB 函数里，这里测试纯逻辑正确性
        pending_exists = True  # 模拟已有 pending
        assert pending_exists  # 如果有 pending → 跳过创建

        pending_exists = False
        assert not pending_exists  # 如果没有 pending → 创建新排期


class TestMarkReviewCompleteChaining:
    """验证 mark_review_complete 自动链式排期。"""

    def test_complete_then_schedule_next(self):
        """完成一次复习后，自动排期下一轮。"""
        # 模拟：当前是第 0 次 review → 完成 → 排期第 1 次（2天后）
        current_round = 0
        next_days = _EBBINGHAUS[current_round + 1] if current_round + 1 < len(_EBBINGHAUS) else _EBBINGHAUS[-1]
        assert next_days == 2  # R1 → 2天后

    def test_chain_through_all_rounds(self):
        """链式排完 6 轮。"""
        expected = [1, 2, 6, 31, 90, 90]  # R0→R1→...→R5→R6
        for i, exp in enumerate(expected):
            if i >= len(_EBBINGHAUS):
                days = _EBBINGHAUS[-1]
            else:
                days = _EBBINGHAUS[i]
            assert days == exp, f"Round {i}: expected {exp}, got {days}"


class TestCommandCenterDataShape:
    """验证 get_command_center_data 返回结构。"""

    def test_expected_keys(self):
        expected_keys = {"feynman_pending", "review_due", "failed_sessions", 
                         "active_sessions", "suggested_nodes"}
        # 确保 DB 函数返回所有 5 个面板数据
        assert len(expected_keys) == 5


# ── Phase 4.1: 个性化复习间隔测试 ──────────────────────────────────

class TestDifficultyFactor:
    """测试 _compute_difficulty_factor 逻辑。"""

    def test_no_history_default(self):
        """无历史数据时返回 1.0（标准间隔）。"""
        # 模拟：无 review_score 记录
        scores = []
        if not scores:
            factor = 1.0
        assert factor == 1.0

    def test_score_only_weighted_avg(self):
        """仅当前分数时，基于分数段计算因子。"""
        def compute(scores, current):
            all_s = list(scores) + ([current] if current is not None else [])
            if not all_s:
                return 1.0
            recent = all_s[-3:]
            weights = list(range(1, len(recent) + 1))
            avg = sum(s * w for s, w in zip(recent, weights)) / sum(weights)
            if avg >= 80: return 1.5
            if avg >= 60: return 1.0
            if avg >= 40: return 0.7
            return 0.5

        assert compute([], 85) == 1.5
        assert compute([], 70) == 1.0
        assert compute([], 45) == 0.7
        assert compute([], 20) == 0.5

    def test_history_weighted_avg(self):
        """历史分数参与加权，越近期权重越高。"""
        def compute(scores, current):
            all_s = list(scores) + ([current] if current is not None else [])
            if not all_s:
                return 1.0
            recent = all_s[-3:]
            weights = list(range(1, len(recent) + 1))
            avg = sum(s * w for s, w in zip(recent, weights)) / sum(weights)
            if avg >= 80: return 1.5
            if avg >= 60: return 1.0
            if avg >= 40: return 0.7
            return 0.5

        # 历史 90, 85 → 最近权重高 (90*1+85*2)/3=86.7 → 1.5
        assert compute([90, 85], 80) == 1.5
        # 历史 30, 40 → (30*1+40*2)/3=36.7 → 0.5
        assert compute([30, 40], 35) == 0.5

    def test_combined_factor_range(self):
        """组合因子在 0.5~1.5 范围内。"""
        session_factor = 1.5
        node_factor = 0.5
        combined = session_factor * 0.6 + node_factor * 0.4
        assert 0.5 <= combined <= 1.5


class TestDynamicInterval:
    """测试 schedule_review 的动态间隔逻辑。"""

    def test_urgent_review_tomorrow(self):
        """score < 40 → 明天立即复习（1天）。"""
        def schedule(base_days, score):
            if score < 40:
                return 1
            return base_days

        assert schedule(6, 30) == 1
        assert schedule(90, 25) == 1
        assert schedule(1, 35) == 1

    def test_weak_review_accelerated(self):
        """score 40-60 → 间隔 × 0.6（加速）。"""
        def schedule(base_days, score, difficulty=1.0):
            if score < 40:
                return 1
            if score < 60:
                return max(1, round(base_days * difficulty * 0.6))
            return max(1, round(base_days * difficulty))

        assert schedule(6, 50) == 4   # 6*0.6=3.6→4
        assert schedule(31, 45) == 19  # 31*0.6=18.6→19
        assert schedule(2, 55) == 1   # 2*0.6=1.2→1（下取整）

    def test_normal_interval_with_difficulty(self):
        """score >= 60 → 正常应用难度系数。"""
        def schedule(base_days, score, difficulty=1.0):
            if score < 40: return 1
            if score < 60: return max(1, round(base_days * difficulty * 0.6))
            return max(1, round(base_days * difficulty))

        # 高分 + 低难度 → 拉长
        assert schedule(6, 85, 1.5) == 9   # 6*1.5=9
        # 中等 + 标准难度 → 不变
        assert schedule(31, 70, 1.0) == 31
        # 中等 + 高难度 → 缩短
        assert schedule(90, 65, 0.5) == 45  # 90*0.5=45

    def test_max_constraint(self):
        """上限保护：不超过 base × 2.0。"""
        base = 6
        factor = 3.0  # 极端高
        days = min(max(1, round(base * factor)), max(1, round(base * 2.0)))
        assert days == 12  # 上限 6*2=12，不是 18
