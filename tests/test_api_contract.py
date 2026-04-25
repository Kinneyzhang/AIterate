"""AIIterate API contract tests — test with running service.

Run:  ~/.hermes/venv/bin/python -m pytest tests/test_api_contract.py -q
Requires: running aiterate.service on port 7070, configured LLM API key

Creates ONE test session total for all deepen tests (cost-saving).
"""

import json
import re
import time
import pytest
import httpx
import subprocess

BASE = "http://192.168.31.222:7070"
_token_cache = None


def _get_token():
    global _token_cache
    if _token_cache is None:
        r = subprocess.run(["curl", "-s", BASE + "/"], capture_output=True, text=True)
        m = re.search(r'AITERATE_TOKEN="([^"]+)"', r.stdout)
        assert m, "Could not extract admin token from page"
        _token_cache = m.group(1)
    return _token_cache


def api(path, method="GET", body=None):
    headers = {"X-Admin-Token": _get_token()}
    if body is not None:
        headers["Content-Type"] = "application/json"
    r = httpx.request(method, BASE + path, headers=headers, json=body, timeout=60.0)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}


# ── Shared test session (created once) ─────────────────────────

@pytest.fixture(scope="module")
def test_session_id():
    """Create one session for all deepen tests, wait for learning status."""
    status, data = api("/api/sessions", "POST", {
        "content": "这是 API 契约测试的测试会话，请忽略。内容：什么是原子操作？",
        "type": "question",
    })
    assert status == 200, f"Create session failed: {data}"
    sid = data["session_id"]
    for _ in range(60):  # up to 60s wait
        s, d = api(f"/api/sessions/{sid}")
        if s == 200 and d.get("status") == "learning":
            break
        if d.get("status") == "error":
            pytest.skip(f"Session creation errored: {d.get('error_msg')}")
        time.sleep(1)
    else:
        pytest.skip("Session did not reach learning status in time")
    yield sid


# ── Test: Deepen Contract ──────────────────────────────────────

class TestDeepenContract:
    """Test deepen endpoint payload compatibility (shared test session)."""

    def test_new_format_take(self, test_session_id):
        """New: {action_type, content} for take."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "action_type": "take",
            "content": "原子操作是指不可被中断的一个或一系列操作，要么全部执行要么全部不执行。",
        })
        assert status == 200, f"New format take failed (status={status}): {data}"
        assert "round_id" in data, f"No round_id: {data}"
        assert data["type"] == "take"

    def test_new_format_press(self, test_session_id):
        """New: {action_type, content} for press."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "action_type": "press",
            "content": "原子操作在数据库事务中如何实现的？",
        })
        assert status == 200, f"New format press failed (status={status}): {data}"
        assert data["type"] == "press"

    def test_old_format_compat(self, test_session_id):
        """Old: {action, text} for backward compatibility."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "action": "take",
            "text": "旧格式 payload 应被兼容。原子操作的核心是 all-or-nothing。",
        })
        assert status == 200, f"Old format failed (status={status}): {data}"
        assert "round_id" in data

    def test_invalid_action_type(self, test_session_id):
        """Invalid action_type should 422."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "action_type": "invalid",
            "content": "测试",
        })
        assert status == 422, f"Expected 422, got {status}"

    def test_empty_content(self, test_session_id):
        """Empty content should 422."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "action_type": "take",
            "content": "",
        })
        assert status == 422, f"Expected 422, got {status}"

    def test_missing_fields(self, test_session_id):
        """Missing required fields should 422."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "other": "field",
        })
        assert status == 422, f"Expected 422, got {status}"

    def test_content_too_long(self, test_session_id):
        """Content > 10000 chars should 422."""
        status, data = api(f"/api/sessions/{test_session_id}/deepen", "POST", {
            "action_type": "press",
            "content": "x" * 10001,
        })
        assert status == 422, f"Expected 422, got {status}"


# ── Test: Command Center ───────────────────────────────────────

class TestCommandCenter:
    """Test command center structure and correctness."""

    def test_structure(self):
        status, data = api("/api/command-center")
        assert status == 200
        for field in ["feynman_pending", "review_due", "failed_sessions", "active_sessions"]:
            assert field in data, f"Missing: {field}"
            assert isinstance(data[field], list)

    def test_no_overlap(self):
        """Active and failed should not overlap."""
        status, data = api("/api/command-center")
        active = {s["id"] for s in data["active_sessions"]}
        failed = {s["id"] for s in data["failed_sessions"]}
        assert not (active & failed), f"Overlap: {active & failed}"


# ── Test: Invariants ──────────────────────────────────────────

class TestInvariants:
    def test_endpoint(self):
        status, data = api("/api/maintenance/check-invariants")
        assert status == 200
        for k in ["ok", "issues", "error_count", "warn_count"]:
            assert k in data, f"Missing: {k}"

    def test_repair_dry_run(self):
        status, data = api("/api/maintenance/repair-invariants?dry_run=true", "POST")
        assert status == 200
        assert data["dry_run"] is True


# ── Test: Stats & Sessions ─────────────────────────────────────

class TestStats:
    def test_stats_structure(self):
        status, data = api("/api/stats")
        assert status == 200
        assert data["total_sessions"] >= data["completed_sessions"]

    def test_sessions_count(self):
        """Verify sessions endpoint returns many (not just 20)."""
        status, data = api("/api/sessions")
        assert status == 200
        assert len(data) > 20, f"Only {len(data)} sessions returned (old limit bug?)"
