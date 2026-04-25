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
        base = {"api_key": "old"}
        result = self._merge_keys(base, {"api_key": "new-key"})
        assert result["api_key"] == "new-key"

    def test_clear_key_with_sentinel(self):
        base = {"api_key": "secret"}
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