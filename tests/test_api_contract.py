"""AIIterate API contract tests — isolated, repeatable, no live LLM calls."""

from app_fixture import AUTH_HEADERS, create_learning_session, setup_isolated_app


def test_auth_contract(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    assert client.get("/api/auth/status").json() == {"authenticated": False}

    bad = client.post("/api/auth/login", json={"token": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"token": "test-admin-token"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    assert client.get("/api/auth/status").json()["authenticated"] is True

    client.post("/api/auth/logout")
    assert client.get("/api/auth/status").json() == {"authenticated": False}


def test_session_create_and_workspace_contract(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server, "什么是原子操作？")

    r = client.get(f"/api/sessions/{sid}/workspace", headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session"]["id"] == sid
    assert data["session"]["status"] == "learning"
    assert isinstance(data["rounds"], list)
    assert "phase" in data
    assert "current_review_group" in data
    assert "unresolved_gaps" in data
    assert "review_report" in data


def test_deepen_payload_contracts_and_validation(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server)

    take = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "我理解核心概念，也能说明边界情况。"},
    )
    assert take.status_code == 200, take.text
    assert take.json()["type"] == "take"
    assert "round_id" in take.json()
    assert "suggested_prompts" in take.json()

    press = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "press", "content": "工程里如何实现？"},
    )
    assert press.status_code == 200, press.text
    assert press.json()["type"] == "press"
    assert "answer" in press.json()

    compat = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action": "take", "text": "旧字段也应该兼容。完整解释核心概念。"},
    )
    assert compat.status_code == 200, compat.text

    for body in [
        {"action_type": "invalid", "content": "x"},
        {"action_type": "take", "content": ""},
        {"other": "field"},
        {"action_type": "press", "content": "x" * 10001},
    ]:
        r = client.post(f"/api/sessions/{sid}/deepen", headers=AUTH_HEADERS, json=body)
        assert r.status_code == 422, r.text


def test_command_center_and_maintenance_contract(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    create_learning_session(client, db, server)

    cc = client.get("/api/command-center", headers=AUTH_HEADERS)
    assert cc.status_code == 200, cc.text
    data = cc.json()
    for field in ["feynman_pending", "review_due", "failed_sessions", "active_sessions"]:
        assert field in data
        assert isinstance(data[field], list)
    assert not ({s["id"] for s in data["active_sessions"]} & {s["id"] for s in data["failed_sessions"]})

    inv = client.get("/api/maintenance/check-invariants", headers=AUTH_HEADERS)
    assert inv.status_code == 200, inv.text
    for key in ["ok", "issues", "error_count", "warn_count"]:
        assert key in inv.json()

    repair = client.post("/api/maintenance/repair-invariants?dry_run=true", headers=AUTH_HEADERS)
    assert repair.status_code == 200, repair.text
    assert repair.json()["dry_run"] is True


def test_stats_and_sessions_contract(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server)

    stats = client.get("/api/stats", headers=AUTH_HEADERS)
    assert stats.status_code == 200, stats.text
    assert stats.json()["total_sessions"] >= stats.json()["completed_sessions"]

    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    assert sessions.status_code == 200, sessions.text
    ids = {s["id"] for s in sessions.json()}
    assert sid in ids
