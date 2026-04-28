from app_fixture import AUTH_HEADERS, create_learning_session, setup_isolated_app


def test_completed_sessions_should_not_show_overdue_review(tmp_path, monkeypatch):
    """Bug fix: 已完成 session 不应显示逾期标记，即使 review_schedule 中有 pending 记录"""
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    sid = create_learning_session(client, db, server, "逾期测试主题")

    # 手动插入一条过期 review_schedule
    from aiterate_db import _exec
    _exec("""
        INSERT INTO review_schedule (session_id, review_date, status, created_at)
        VALUES (:sid, '2020-01-01', 'pending', '2020-01-01')
    """, {"sid": sid})

    # 完成 session（但 review_schedule 残留 pending）
    _exec("UPDATE sessions SET status = 'completed' WHERE id = :sid", {"sid": sid})

    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    assert sessions.status_code == 200
    for s in sessions.json():
        if s["id"] == sid:
            assert not s.get("has_overdue_review"), \
                "已完成 session 不应标记逾期，即使有残留的 pending review"

    # 验证：同一个 session 如果未完成，应该显示逾期
    sid2 = create_learning_session(client, db, server, "未完成逾期测试")
    _exec("""
        INSERT INTO review_schedule (session_id, review_date, status, created_at)
        VALUES (:sid, '2020-01-01', 'pending', '2020-01-01')
    """, {"sid": sid2})

    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    assert sessions.status_code == 200
    uncompleted = [s for s in sessions.json() if s["id"] == sid2]
    assert len(uncompleted) == 1
    assert uncompleted[0].get("has_overdue_review"), \
        "未完成 session 有逾期 review，应显示逾期标记"


def test_pin_survives_grouped_sort(tmp_path, monkeypatch):
    """Bug fix: 置顶排序应在侧边栏分组后仍然有效

    验证后端 pin 后 session 出现在列表最前，即使用户对另一个
    session 做了后续操作（updated_at 更新）也不应影响置顶排序。
    """
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    # 创建两个 session
    first = create_learning_session(client, db, server, "第一")
    second = create_learning_session(client, db, server, "第二")

    # pin second session（较低优先级的 session）
    pinned = client.post(
        f"/api/sessions/{first}/pin",
        headers=AUTH_HEADERS,
        json={"pinned": True},
    )
    assert pinned.status_code == 200

    # 验证列表顺序：first（已置顶）应排在 second 前面
    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    assert sessions.status_code == 200
    ids = [s["id"] for s in sessions.json()]
    first_idx = ids.index(first)
    second_idx = ids.index(second)
    assert first_idx < second_idx, \
        f"置顶 session ({first}) 应排在前面，实际 first@{first_idx} second@{second_idx}"

    # 更新 second 的 title（使其 updated_at 变新）—— 不应影响置顶排序
    client.patch(
        f"/api/sessions/{second}/title",
        headers=AUTH_HEADERS,
        json={"title": "第二更新了"},
    )

    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    ids = [s["id"] for s in sessions.json()]
    first_idx = ids.index(first)
    second_idx = ids.index(second)
    assert first_idx < second_idx, \
        f"非置顶 session 更新后，置顶 session 仍应排在前面"

    # unpin 后 second 因 updated_at 更新应排在前面
    client.post(
        f"/api/sessions/{first}/pin",
        headers=AUTH_HEADERS,
        json={"pinned": False},
    )

    sessions = client.get("/api/sessions", headers=AUTH_HEADERS)
    ids = [s["id"] for s in sessions.json()]
    assert ids.index(second) < ids.index(first), \
        "取消置顶后，updated_at 更新的 session 应排在前面"
