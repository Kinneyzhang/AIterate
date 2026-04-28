"""AIIterate state-machine tests — isolated and repeatable."""

from app_fixture import AUTH_HEADERS, create_learning_session, setup_isolated_app


def test_invalid_transitions_return_409(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server)

    # Cannot complete feynman before entering feynman state.
    r = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": 1, "answers": ["x"]},
    )
    assert r.status_code == 409

    # Cannot reopen a normal learning session.
    r = client.post(f"/api/sessions/{sid}/reopen", headers=AUTH_HEADERS)
    assert r.status_code == 409

    # Cannot start feynman before at least one take round.
    r = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS)
    assert r.status_code == 409


def test_feynman_pending_group_is_idempotent_and_requires_matching_answers(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server)

    take = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "完整说明核心概念和工程边界。"},
    )
    assert take.status_code == 200, take.text

    first = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS)
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data.get("reused") is not True

    second = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS)
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["group_id"] == first_data["group_id"]
    assert second_data["round_ids"] == first_data["round_ids"]
    assert second_data.get("reused") is True

    bad = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": first_data["group_id"], "answers": ["only one answer"]},
    )
    assert bad.status_code == 400


def test_feynman_pass_creates_review_and_rejects_double_submit(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch, review_scores=[88])
    sid = create_learning_session(client, db, server)
    client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "完整说明核心概念和工程边界。"},
    )
    start = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS).json()
    answers = ["完整回答核心概念、例子和边界。" for _ in start["questions"]]

    done = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": start["group_id"], "answers": answers},
    )
    assert done.status_code == 200, done.text
    assert done.json()["passed"] is True
    assert done.json()["new_status"] == "completed"

    session = client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS).json()
    assert session["status"] == "completed"
    report = session["review_report"]
    if isinstance(report, str):
        import json
        report = json.loads(report)
    assert report["passed"] is True
    assert db.get_session_review_schedule(sid)

    again = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": start["group_id"], "answers": answers},
    )
    assert again.status_code == 409


def test_feynman_fail_returns_to_revising_with_correction_plan(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch, review_scores=[35])
    sid = create_learning_session(client, db, server)
    client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "粗略理解。"},
    )
    start = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS).json()

    done = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": start["group_id"], "answers": ["不完整" for _ in start["questions"]]},
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["passed"] is False
    assert body["new_status"] == "revising"
    assert body["correction_plan"]
    assert client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS).json()["status"] == "revising"


def test_review_skip_requires_existing_pending_row(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch, review_scores=[90])
    sid = create_learning_session(client, db, server)
    client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "完整说明核心概念和工程边界。"},
    )
    start = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS).json()
    client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": start["group_id"], "answers": ["完整回答" for _ in start["questions"]]},
    )
    rid = db.get_session_review_schedule(sid)[0]["id"]

    missing = client.post("/api/review/999999/skip", headers=AUTH_HEADERS)
    assert missing.status_code == 404

    skipped = client.post(f"/api/review/{rid}/skip", headers=AUTH_HEADERS)
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["status"] == "skipped"
    assert db.get_session_review_schedule(sid)[0]["status"] == "skipped"


def test_repair_multiple_pending_feynman_groups(tmp_path, monkeypatch):
    """修复：一个 session 有多个 pending feynman group 时，取消多余的，保留最新的。"""
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    # 创建 session 并推进到 feynman
    sid = create_learning_session(client, db, server)
    # take
    r = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "完整理解：幂等性指多次执行结果相同，核心在于去重和状态管理。"},
    )
    assert r.status_code == 200

    # start feynman（正常分支：只有一个 pending group）
    r = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    group_id = data["group_id"]

    # 模拟 bug：直接用 DB 插入两个额外的 pending feynman groups
    from sqlalchemy import text
    seq_base = db._fetch_one("SELECT COALESCE(MAX(seq), 0) AS m FROM rounds WHERE session_id = :sid", {"sid": sid})["m"]
    for extra_gid in [group_id + 100, group_id + 200]:
        seq_base += 1
        db._exec(
            "INSERT INTO rounds (session_id, seq, type, status, group_id, input, output, score, created_at) "
            "VALUES (:sid, :seq, 'feynman', 'pending', :gid, '额外问题', NULL, NULL, datetime('now'))",
            {"sid": sid, "seq": seq_base, "gid": extra_gid},
        )

    # 验证：check_invariants 检测到问题
    inv = db.check_invariants()
    assert not inv["ok"], f"Expected invariant violation, got: {inv}"
    assert any(i["type"] == "multiple_pending_feynman_groups" for i in inv["issues"])

    # 修复
    repaired = db.repair_invariants(dry_run=False)
    assert any(r["issue"] == "multiple_pending_feynman_groups" for r in repaired["repairs"])

    # 验证：修复后只有 1 个 pending group
    pending = db._fetch_all(
        "SELECT group_id, status FROM rounds "
        "WHERE session_id = :sid AND type = 'feynman' AND status = 'pending'",
        {"sid": sid},
    )
    assert len(pending) <= 2, f"Expected <=2 pending rounds, got {len(pending)}: {pending}"
    groups = set(r["group_id"] for r in pending)
    assert len(groups) == 1, f"Expected 1 pending group, got {len(groups)}: {groups}"

    # 多余的应该被取消
    cancelled = db._fetch_all(
        "SELECT group_id FROM rounds "
        "WHERE session_id = :sid AND type = 'feynman' AND status = 'cancelled'",
        {"sid": sid},
    )
    assert len(cancelled) > 0, "Expected some cancelled rounds"

    # 最终 invariants 应 clean
    inv2 = db.check_invariants()
    assert inv2["ok"], f"Invariants should be clean after repair, got: {inv2}"


def test_take_from_learning_state_before_viewing_ai_answer(tmp_path, monkeypatch):
    """验证：用户可以从 learning 状态直接写理解（不看 AI 回答），
    之后 workspace 包含 take round 且 AI material 仍然可用。"""
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server)

    # 确认 session 在 learning 状态，有 AI 回答
    s = client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS)
    assert s.status_code == 200
    session = s.json()
    assert session["status"] == "learning"
    assert session.get("material")  # AI 回答已生成

    # 用户不看 AI 回答，直接写理解
    take_content = "我对幂等性的理解：指同一个操作执行多次，结果保持一致。"
    r = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": take_content},
    )
    assert r.status_code == 200, r.text

    # 验证 workspace 包含 take round
    ws = client.get(f"/api/sessions/{sid}/workspace", headers=AUTH_HEADERS)
    assert ws.status_code == 200
    workspace = ws.json()
    assert workspace["phase"] in ("deepening", "learning")
    rounds = workspace["rounds"]
    take_rounds = [r for r in rounds if r["type"] == "take"]
    assert len(take_rounds) >= 1
    assert take_rounds[0]["input"] == take_content

    # AI 回答仍然存在
    assert workspace["session"].get("material")
