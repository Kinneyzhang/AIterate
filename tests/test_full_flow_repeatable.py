"""Repeatable end-to-end learning flows on an isolated SQLite database."""

from app_fixture import AUTH_HEADERS, create_learning_session, setup_isolated_app


def test_full_flow_pass_path_is_repeatable(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch, review_scores=[86])
    sid = create_learning_session(client, db, server, "什么是幂等 API？")

    take = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "完整解释幂等性的核心概念、HTTP PUT/DELETE 示例和重复提交边界。"},
    )
    assert take.status_code == 200, take.text
    assert take.json()["score"] >= 60

    press = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "press", "content": "幂等性和重试机制如何配合？"},
    )
    assert press.status_code == 200, press.text
    assert "追问" in press.json()["answer"]

    start = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS)
    assert start.status_code == 200, start.text
    questions = start.json()["questions"]
    assert len(questions) == 2

    done = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": start.json()["group_id"], "answers": ["完整回答核心概念、例子和边界。" for _ in questions]},
    )
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["passed"] is True
    assert result["new_status"] == "completed"

    ws = client.get(f"/api/sessions/{sid}/workspace", headers=AUTH_HEADERS).json()
    assert ws["session"]["status"] == "completed"
    assert ws["review_report"]["passed"] is True
    assert len(ws["latest_review_result"]) == 2


def test_full_flow_fail_then_revise_then_pass(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch, review_scores=[30, 91])
    sid = create_learning_session(client, db, server, "什么是数据库事务隔离级别？")

    client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "只知道事务隔离和并发有关。"},
    )
    first = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS).json()
    failed = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": first["group_id"], "answers": ["不完整" for _ in first["questions"]]},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["new_status"] == "revising"
    assert failed.json()["correction_plan"]["weak_concepts"]

    revise = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "完整解释脏读、不可重复读、幻读、MVCC 和锁的边界。"},
    )
    assert revise.status_code == 200, revise.text

    second = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS).json()
    assert second["group_id"] != first["group_id"]
    passed = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": second["group_id"], "answers": ["完整回答核心概念、例子和边界。" for _ in second["questions"]]},
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()["passed"] is True
    assert client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS).json()["status"] == "completed"


def test_manual_completion_is_allowed_from_learning_deepening_and_feynman(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    learning_sid = create_learning_session(client, db, server, "什么是布隆过滤器？")
    learning_done = client.post(f"/api/sessions/{learning_sid}/complete", headers=AUTH_HEADERS)
    assert learning_done.status_code == 200, learning_done.text
    assert client.get(f"/api/sessions/{learning_sid}", headers=AUTH_HEADERS).json()["status"] == "completed"
    assert db.get_session_review_schedule(learning_sid)

    deepening_sid = create_learning_session(client, db, server, "什么是 B 树？")
    take = client.post(
        f"/api/sessions/{deepening_sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "我能解释 B 树的平衡、多路搜索和磁盘访问优化。"},
    )
    assert take.status_code == 200, take.text
    deepening_done = client.post(f"/api/sessions/{deepening_sid}/complete", headers=AUTH_HEADERS)
    assert deepening_done.status_code == 200, deepening_done.text
    assert client.get(f"/api/sessions/{deepening_sid}", headers=AUTH_HEADERS).json()["status"] == "completed"

    feynman_sid = create_learning_session(client, db, server, "什么是 MVCC？")
    client.post(
        f"/api/sessions/{feynman_sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "我能解释版本链、快照读、当前读和隔离级别。"},
    )
    started = client.post(f"/api/sessions/{feynman_sid}/start-feynman", headers=AUTH_HEADERS)
    assert started.status_code == 200, started.text
    feynman_done = client.post(f"/api/sessions/{feynman_sid}/complete", headers=AUTH_HEADERS)
    assert feynman_done.status_code == 200, feynman_done.text
    assert client.get(f"/api/sessions/{feynman_sid}", headers=AUTH_HEADERS).json()["status"] == "completed"
    rounds = db.get_rounds(feynman_sid)
    assert [r["status"] for r in rounds if r["type"] == "feynman"] == ["cancelled", "cancelled"]


def test_isolated_database_starts_clean_each_run(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    assert client.get("/api/sessions", headers=AUTH_HEADERS).json() == []
    create_learning_session(client, db, server)
    assert len(client.get("/api/sessions", headers=AUTH_HEADERS).json()) == 1
