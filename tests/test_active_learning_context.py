from __future__ import annotations

import asyncio

import pytest

from app_fixture import AUTH_HEADERS, setup_isolated_app, create_learning_session


def _process_next_inbox_job(db, server):
    job = db.claim_pending_job()
    assert job is not None, "expected pending inbox generation job"
    asyncio.run(server._process_generate_inbox_questions(job["id"], job))
    return job


def _fake_questions(label: str):
    return [
        {
            "question": f"{label} 的关键问题 {i}？",
            "why": f"来自 {label} 的第 {i} 个学习切口。",
            "angle": "concept",
            "depth": "medium",
            "related_concepts": [label, "主动上下文"],
            "suggested_type": "question",
        }
        for i in range(1, 6)
    ]


def test_inbox_creates_entry_and_selected_session_keeps_source_provenance(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    async def fake_generate_inbox_questions(content: str, direction: str | None = None):
        return {"questions": _fake_questions("MVCC")}

    monkeypatch.setattr(server.ai, "generate_inbox_questions", fake_generate_inbox_questions, raising=False)

    created = client.post(
        "/api/inbox",
        headers=AUTH_HEADERS,
        json={"content": "MVCC 快照读和当前读的差异", "source_type": "telegram"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]
    assert created.json()["entry_id"]

    _process_next_inbox_job(db, server)

    detail = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS)
    assert detail.status_code == 200, detail.text
    item = detail.json()["item"]
    entry_id = item["entry_id"]
    assert entry_id == created.json()["entry_id"]

    entries = client.get("/api/entries", headers=AUTH_HEADERS).json()
    entry = next(e for e in entries if e["id"] == entry_id)
    assert entry["content"] == "MVCC 快照读和当前读的差异"
    assert entry["metadata"]["origin"] == "inbox"
    assert entry["metadata"]["inbox_item_id"] == item_id

    q = detail.json()["questions"][0]
    assert q["provenance"]["entry_id"] == entry_id
    selected = client.post(f"/api/inbox/questions/{q['id']}/select", headers=AUTH_HEADERS, json={"web_search": False})
    assert selected.status_code == 200, selected.text
    sid = selected.json()["session_id"]
    session = client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS).json()
    assert session["source_entry_id"] == entry_id


def test_legacy_inbox_items_are_backfilled_to_entries(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    item_id = db._insert_returning_id(
        """INSERT INTO inbox_items (title, content, source_type, status, created_at, updated_at)
           VALUES (:title, :content, :source_type, 'ready', datetime('now'), datetime('now')) RETURNING id""",
        {"title": "旧素材", "content": "旧 Inbox 里的 MVCC 笔记", "source_type": "text"},
    )
    assert db.get_inbox_item(item_id)["entry_id"] is None

    changed = db.backfill_inbox_entries()

    assert changed == 1
    item = db.get_inbox_item(item_id)
    assert item["entry_id"]
    entry = db.get_entry(item["entry_id"])
    assert entry["content"] == "旧 Inbox 里的 MVCC 笔记"
    assert entry["kind"] == "inbox"
    assert entry["metadata"]["backfilled_from"] == "inbox_items"
    assert db.backfill_inbox_entries() == 0


def test_threads_can_group_entries_sessions_and_expose_provenance(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server, "PostgreSQL MVCC 如何避免不可重复读？")
    entry = client.post(
        "/api/entries",
        headers=AUTH_HEADERS,
        json={"content": "MVCC 读一致性笔记", "kind": "note", "source_type": "text"},
    )
    assert entry.status_code == 200, entry.text
    entry_id = entry.json()["id"]

    created = client.post(
        "/api/threads",
        headers=AUTH_HEADERS,
        json={"title": "数据库事务", "kind": "topic", "summary": "事务隔离与一致性"},
    )
    assert created.status_code == 200, created.text
    thread_id = created.json()["id"]

    for payload in [
        {"item_type": "entry", "item_id": entry_id, "relation": "source", "provenance": {"reason": "同属 MVCC 主题"}},
        {"item_type": "session", "item_id": sid, "relation": "learning", "provenance": {"reason": "学习会话"}},
    ]:
        r = client.post(f"/api/threads/{thread_id}/items", headers=AUTH_HEADERS, json=payload)
        assert r.status_code == 200, r.text

    patched = client.patch(f"/api/sessions/{sid}/thread", headers=AUTH_HEADERS, json={"thread_id": thread_id})
    assert patched.status_code == 200, patched.text
    assert patched.json()["session"]["active_thread_id"] == thread_id

    detail = client.get(f"/api/threads/{thread_id}", headers=AUTH_HEADERS)
    assert detail.status_code == 200, detail.text
    items = detail.json()["items"]
    assert {x["item_type"] for x in items} == {"entry", "session"}
    assert all(x["provenance"] for x in items)


def test_related_context_returns_sources_with_provenance(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server, "MVCC 快照读如何工作？")
    other = create_learning_session(client, db, server, "MVCC 当前读为什么会加锁？")
    entry = client.post(
        "/api/entries",
        headers=AUTH_HEADERS,
        json={"content": "MVCC 的快照读、当前读和幻读案例", "kind": "note"},
    )
    assert entry.status_code == 200, entry.text
    db.create_gaps_from_take(sid, None, {"gaps": ["MVCC 快照可见性规则还不清楚"]})

    related = client.get(f"/api/sessions/{sid}/related-context", headers=AUTH_HEADERS)
    assert related.status_code == 200, related.text
    data = related.json()
    assert any(x["type"] == "session" and x["id"] == other for x in data["items"])
    assert any(x["type"] == "entry" for x in data["items"])
    assert any(x["type"] == "gap" for x in data["items"])
    assert all(x["provenance"] and x["provenance"][0]["reason"] for x in data["items"])


def test_learning_agents_are_collaborators_with_provenance(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server, "Bloom Filter 如何处理缓存穿透？")

    agents = client.get("/api/agents", headers=AUTH_HEADERS)
    assert agents.status_code == 200, agents.text
    ids = {a["id"] for a in agents.json()}
    assert {"question_alchemist", "context_detective", "feynman_coach", "review_scheduler", "action_translator"}.issubset(ids)

    run = client.post(
        "/api/agents/context_detective/run",
        headers=AUTH_HEADERS,
        json={"target_type": "session", "target_id": sid},
    )
    assert run.status_code == 200, run.text
    out = run.json()
    assert out["agent_id"] == "context_detective"
    assert out["output"]["suggestions"]
    assert out["provenance"]

    disabled = client.patch("/api/agents/context_detective", headers=AUTH_HEADERS, json={"enabled": False})
    assert disabled.status_code == 200, disabled.text
    blocked = client.post(
        "/api/agents/context_detective/run",
        headers=AUTH_HEADERS,
        json={"target_type": "session", "target_id": sid},
    )
    assert blocked.status_code == 409


def test_learning_briefs_and_personal_synthesis_include_provenance(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    sid = create_learning_session(client, db, server, "PostgreSQL MVCC 与幻读")
    db.create_gaps_from_take(sid, None, {"gaps": ["幻读与快照隔离的关系需要例子"]})
    client.post("/api/entries", headers=AUTH_HEADERS, json={"content": "今天重新理解 MVCC 和幻读", "kind": "note"})

    brief = client.get("/api/briefs/learning?period=daily", headers=AUTH_HEADERS)
    assert brief.status_code == 200, brief.text
    b = brief.json()
    assert b["period"] == "daily"
    assert b["suggested_focus"]
    assert all(item["provenance"] for item in b["suggested_focus"])

    synth = client.post("/api/me/synthesis", headers=AUTH_HEADERS, json={"query": "MVCC"})
    assert synth.status_code == 200, synth.text
    data = synth.json()
    assert "MVCC" in data["answer"]
    assert data["evidence"]
    assert data["provenance"]
    assert data["next_steps"]


def test_learning_brief_entry_focus_links_back_to_inbox_item(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    created = client.post(
        "/api/inbox",
        headers=AUTH_HEADERS,
        json={"content": "云南昆明旅行素材", "source_type": "telegram"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]

    brief = client.get("/api/briefs/learning?period=daily", headers=AUTH_HEADERS)
    assert brief.status_code == 200, brief.text
    entries = [x for x in brief.json()["suggested_focus"] if x["type"] == "entry"]
    assert entries
    assert entries[0]["target"] == {"type": "inbox_item", "id": item_id}


def test_personal_synthesis_handles_json_review_report_dict(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    monkeypatch.setattr(db, "get_entries", lambda limit=100, q=None, kind=None, status=None: [])
    monkeypatch.setattr(
        db,
        "get_recent_sessions",
        lambda limit=100: [
            {
                "id": 1,
                "title": "PostgreSQL MVCC 与隔离级别",
                "content": "",
                "material": "",
                "review_report": {"final_summary": "MVCC 用快照可见性支撑一致性读。"},
            }
        ],
    )

    synth = client.post("/api/me/synthesis", headers=AUTH_HEADERS, json={"query": "MVCC"})
    assert synth.status_code == 200, synth.text
    assert "MVCC" in synth.json()["answer"]


def test_personal_synthesis_rejects_empty_query(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)
    r = client.post("/api/me/synthesis", headers=AUTH_HEADERS, json={"query": "   "})
    assert r.status_code == 422
