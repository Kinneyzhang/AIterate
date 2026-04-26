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
