"""Session action menu API tests — rename, pin, delete, share summary."""

from app_fixture import AUTH_HEADERS, create_learning_session, setup_isolated_app


def test_session_rename_pin_and_delete_contract(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    first = create_learning_session(client, db, server, "第一个主题")
    second = create_learning_session(client, db, server, "第二个主题")

    renamed = client.patch(
        f"/api/sessions/{first}/title",
        headers=AUTH_HEADERS,
        json={"title": "  新标题  "},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["session"]["title"] == "新标题"

    bad = client.patch(
        f"/api/sessions/{first}/title",
        headers=AUTH_HEADERS,
        json={"title": ""},
    )
    assert bad.status_code == 422

    pinned = client.post(
        f"/api/sessions/{first}/pin",
        headers=AUTH_HEADERS,
        json={"pinned": True},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["session"]["pinned_at"]
    assert pinned.json()["session"]["updated_at"] == renamed.json()["session"]["updated_at"]

    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    assert sessions.status_code == 200, sessions.text
    assert sessions.json()[0]["id"] == first
    assert sessions.json()[0]["pinned_at"]

    # Make second definitively newer; unpin must restore normal updated_at ordering.
    second_renamed = client.patch(
        f"/api/sessions/{second}/title",
        headers=AUTH_HEADERS,
        json={"title": "第二个主题较新"},
    )
    assert second_renamed.status_code == 200, second_renamed.text

    unpinned = client.post(
        f"/api/sessions/{first}/pin",
        headers=AUTH_HEADERS,
        json={"pinned": False},
    )
    assert unpinned.status_code == 200, unpinned.text
    assert unpinned.json()["session"]["pinned_at"] is None
    assert unpinned.json()["session"]["updated_at"] == pinned.json()["session"]["updated_at"]
    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    assert sessions.status_code == 200, sessions.text
    assert sessions.json()[0]["id"] == second

    deleted = client.delete(f"/api/sessions/{second}", headers=AUTH_HEADERS)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"ok": True, "deleted_id": second}
    missing = client.get(f"/api/sessions/{second}", headers=AUTH_HEADERS)
    assert missing.status_code == 404


def test_session_share_summary_contains_learning_deepening_and_feynman(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server, "什么是 API 幂等性？")

    take = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "take", "content": "我理解核心概念，也能说明边界情况。"},
    )
    assert take.status_code == 200, take.text

    press = client.post(
        f"/api/sessions/{sid}/deepen",
        headers=AUTH_HEADERS,
        json={"action_type": "press", "content": "工程里如何防止重复下单？"},
    )
    assert press.status_code == 200, press.text

    started = client.post(f"/api/sessions/{sid}/start-feynman", headers=AUTH_HEADERS)
    assert started.status_code == 200, started.text
    group_id = started.json()["group_id"]

    completed = client.post(
        f"/api/sessions/{sid}/complete-feynman",
        headers=AUTH_HEADERS,
        json={"group_id": group_id, "answers": ["解释核心概念，并给出幂等键例子。", "反例是没有唯一约束的 POST 重试。"]},
    )
    assert completed.status_code == 200, completed.text

    shared = client.get(f"/api/sessions/{sid}/share", headers=AUTH_HEADERS)
    assert shared.status_code == 200, shared.text
    data = shared.json()
    assert data["session"]["id"] == sid
    assert data["learn"]["question"] == "什么是 API 幂等性？"
    assert "结构化回答" in data["learn"]["material"]
    assert [r["type"] for r in data["deepen_rounds"]] == ["take", "press"]
    assert data["deepen_rounds"][0]["user"] == "我理解核心概念，也能说明边界情况。"
    assert "工程里如何防止重复下单" in data["deepen_rounds"][1]["user"]
    assert len(data["feynman_groups"]) == 1
    assert len(data["feynman_groups"][0]["items"]) == 2
    assert data["feynman_groups"][0]["items"][0]["question"] == "请用自己的话解释核心概念。"
    assert "幂等键" in data["feynman_groups"][0]["items"][0]["answer"]
    assert data["review_report"]["final_score"] == 86
