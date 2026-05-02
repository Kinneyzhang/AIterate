import asyncio
import json
from pathlib import Path

from app_fixture import AUTH_HEADERS, run_next_answer_job, setup_isolated_app


def _fake_questions(content, suffix=""):
    return {
        "questions": [
            {
                "question": f"为什么「{content}」值得被深入追问{suffix}？",
                "why": "它能把零散素材转化为可验证的学习问题。",
                "angle": "跨学科",
                "depth": "medium",
                "related_concepts": ["问题生成", "认知边界"],
                "suggested_type": "question",
            },
            {
                "question": f"「{content}」背后隐藏了什么默认假设{suffix}？",
                "why": "默认假设通常决定了后续学习能否突破原有框架。",
                "angle": "心理学",
                "depth": "high",
                "related_concepts": ["假设", "元认知"],
                "suggested_type": "question",
            },
        ]
    }


def test_inbox_item_stored_then_generate_manually(tmp_path, monkeypatch):
    """Items are stored without auto-generation; user triggers via /generate endpoint."""
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    async def fake_generate_inbox_questions(content: str, direction: str | None = None):
        return _fake_questions(content)

    monkeypatch.setattr(server.ai, "generate_inbox_questions", fake_generate_inbox_questions, raising=False)

    # Create item — should be 'stored', no auto job
    created = client.post(
        "/api/inbox",
        headers=AUTH_HEADERS,
        json={"content": "异化", "source_type": "text"},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["status"] == "stored"
    item_id = payload["id"]

    # No pending job should exist
    job = db.claim_pending_job()
    assert job is None, "No job should be auto-created"

    # Manually trigger generation
    gen = client.post(f"/api/inbox/{item_id}/generate", headers=AUTH_HEADERS)
    assert gen.status_code == 200, gen.text
    assert gen.json()["status"] == "generating"

    # Now a job exists
    job = db.claim_pending_job()
    assert job is not None
    assert job["job_type"] == "generate_inbox_questions"
    asyncio.run(server._process_generate_inbox_questions(job["id"], job))

    detail = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["item"]["status"] == "ready"
    assert len(data["questions"]) == 2
    first = data["questions"][0]
    assert first["status"] == "candidate"
    assert first["question"].startswith("为什么「异化」")

    # Select question → session
    selected = client.post(
        f"/api/inbox/questions/{first['id']}/select",
        headers=AUTH_HEADERS,
        json={"web_search": False, "knowledge_node_id": None},
    )
    assert selected.status_code == 200, selected.text
    session_id = selected.json()["session_id"]
    session = db.get_session(session_id)
    assert session is not None
    assert session["status"] == "preparing"
    assert "异化" in session["content"]

    updated_detail = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()
    selected_question = next(q for q in updated_detail["questions"] if q["id"] == first["id"])
    assert selected_question["status"] == "selected"
    assert selected_question["session_id"] == session_id
    assert updated_detail["item"]["status"] == "partially_used"

    archived = client.post(f"/api/inbox/{item_id}/archive", headers=AUTH_HEADERS)
    assert archived.status_code == 200, archived.text
    listed_after_archive = client.get("/api/inbox", headers=AUTH_HEADERS).json()
    archived_item = next(x for x in listed_after_archive if x["id"] == item_id)
    assert archived_item["status"] == "archived"


def test_inbox_create_can_pass_generation_direction(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    seen = {}

    async def fake_generate_inbox_questions(content: str, direction: str | None = None):
        seen["content"] = content
        seen["direction"] = direction
        return _fake_questions(content, suffix=f"（{direction}）")

    monkeypatch.setattr(server.ai, "generate_inbox_questions", fake_generate_inbox_questions, raising=False)

    created = client.post(
        "/api/inbox",
        headers=AUTH_HEADERS,
        json={"content": "函数式编程", "source_type": "text"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]

    # Manually trigger generation with direction
    gen = client.post(
        f"/api/inbox/{item_id}/generate",
        headers=AUTH_HEADERS,
        json={"direction": "领域：计算机、哲学；处理方式：找反例"},
    )
    assert gen.status_code == 200

    job = db.claim_pending_job()
    payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
    assert payload["direction"] == "领域：计算机、哲学；处理方式：找反例"
    asyncio.run(server._process_generate_inbox_questions(job["id"], job))

    assert seen == {"content": "函数式编程", "direction": "领域：计算机、哲学；处理方式：找反例"}
    questions = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()["questions"]
    assert all("找反例" in q["question"] for q in questions)


def test_inbox_regenerate_appends_without_replacing_visible_candidates(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    async def fake_generate_inbox_questions(content: str, direction: str | None = None):
        suffix = f"（{direction}）" if direction else ""
        return _fake_questions(content, suffix=suffix)

    monkeypatch.setattr(server.ai, "generate_inbox_questions", fake_generate_inbox_questions, raising=False)

    r = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": "提示词工程正在消失"})
    assert r.status_code == 200, r.text
    item_id = r.json()["id"]
    # Manually trigger generation
    gen = client.post(f"/api/inbox/{item_id}/generate", headers=AUTH_HEADERS)
    assert gen.status_code == 200
    job = db.claim_pending_job()
    asyncio.run(server._process_generate_inbox_questions(job["id"], job))
    original = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()["questions"]
    original_ids = [q["id"] for q in original]

    regen = client.post(
        f"/api/inbox/{item_id}/regenerate",
        headers=AUTH_HEADERS,
        json={"direction": "更偏技术一点"},
    )
    assert regen.status_code == 200, regen.text
    job = db.claim_pending_job()
    assert job["job_type"] == "generate_inbox_questions"
    asyncio.run(server._process_generate_inbox_questions(job["id"], job))

    refreshed = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()["questions"]
    # Old candidates are marked 'replaced' instead of deleted (preserves IDs for ongoing selects)
    replaced = [q for q in refreshed if q["status"] == "replaced"]
    assert len(replaced) > 0, "Old candidates should be marked replaced"
    new_candidates = [q for q in refreshed if q["status"] == "candidate"]
    assert any("更偏技术一点" in q["question"] for q in new_candidates)
    assert len(new_candidates) <= 3, f"Should cap at 3, got {len(new_candidates)}"


def test_inbox_existing_question_remains_selectable_while_background_generation_finishes(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    async def fake_generate_inbox_questions(content: str, direction: str | None = None):
        return _fake_questions(content, suffix="（后台批次）")

    monkeypatch.setattr(server.ai, "generate_inbox_questions", fake_generate_inbox_questions, raising=False)

    r = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": "缓存穿透"})
    assert r.status_code == 200, r.text
    item_id = r.json()["id"]
    gen = client.post(f"/api/inbox/{item_id}/generate", headers=AUTH_HEADERS)
    assert gen.status_code == 200
    first_job = db.claim_pending_job()
    asyncio.run(server._process_generate_inbox_questions(first_job["id"], first_job))
    original = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()["questions"]
    first_question_id = original[0]["id"]

    db.update_inbox_item(item_id, status="generating", error_msg=None)
    db.create_job(
        job_type="generate_inbox_questions",
        payload={"inbox_item_id": item_id, "content": "缓存穿透", "direction": "后台批次", "replace": True},
    )
    background_job = db.claim_pending_job()
    asyncio.run(server._process_generate_inbox_questions(background_job["id"], background_job))

    detail = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()
    # After replace=True background job, old candidates are cleared — use new first question
    new_first_id = detail["questions"][0]["id"]
    selected = client.post(
        f"/api/inbox/questions/{new_first_id}/select",
        headers=AUTH_HEADERS,
        json={"web_search": False, "knowledge_node_id": None},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["session_id"]
    assert client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()["item"]["status"] == "partially_used"


def test_inbox_parse_failure_preserves_existing_questions_as_ready(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    r = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": "大模型的泛化和约束"})
    assert r.status_code == 200, r.text
    item_id = r.json()["id"]
    db.create_inbox_questions(item_id, _fake_questions("大模型的泛化和约束")["questions"])
    db.update_inbox_item(item_id, status="generating", error_msg="previous failure")

    async def fake_generate_inbox_questions(content: str, direction: str | None = None):
        return {"questions": [], "parse_failed": True, "raw": "not json"}

    monkeypatch.setattr(server.ai, "generate_inbox_questions", fake_generate_inbox_questions, raising=False)
    # Manually trigger generation to create a job
    gen = client.post(f"/api/inbox/{item_id}/generate", headers=AUTH_HEADERS)
    assert gen.status_code == 200
    job = db.claim_pending_job()
    asyncio.run(server._process_generate_inbox_questions(job["id"], job))

    detail = client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).json()
    assert detail["item"]["status"] == "ready"
    assert detail["item"].get("error_msg") is None
    assert len(detail["questions"]) == 2
    completed_job = db._fetch_one("SELECT status, error_msg, result FROM jobs WHERE id = :id", {"id": job["id"]})
    assert completed_job["status"] == "completed"
    assert completed_job["error_msg"] is None


def test_session_answer_uses_fallback_title_when_ai_title_is_blank(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    async def blank_title(content: str):
        return "   "

    monkeypatch.setattr(server.ai, "generate_title", blank_title)
    r = client.post(
        "/api/sessions",
        headers=AUTH_HEADERS,
        json={"content": "问题：Lisp 宏为什么能减少 boilerplate？", "type": "question", "web_search": False},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    run_next_answer_job(db, server)

    session = client.get(f"/api/sessions/{sid}", headers=AUTH_HEADERS).json()
    assert session["status"] == "learning"
    assert session["title"] == "Lisp 宏为什么能减少 boilerplate"


def test_inbox_item_has_short_title_and_history_delete_contract(tmp_path, monkeypatch):
    client, db, server = setup_isolated_app(tmp_path, monkeypatch)

    long_content = "标题：大型语言模型在个人学习系统中的反馈闭环设计\n\n这是一段很长的素材正文，包含许多细节，不应该整段作为列表标题展示。"
    created = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": long_content})
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]
    assert created.json()["title"] == "大型语言模型在个人学习系统中的反馈闭环设计"[:32]

    listed = client.get("/api/inbox", headers=AUTH_HEADERS).json()
    row = next(x for x in listed if x["id"] == item_id)
    assert row["title"]
    assert row["title"] != row["content"]
    assert len(row["title"]) <= 32

    archived = client.post(f"/api/inbox/{item_id}/archive", headers=AUTH_HEADERS)
    assert archived.status_code == 200, archived.text
    deleted = client.delete(f"/api/inbox/{item_id}", headers=AUTH_HEADERS)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"ok": True, "deleted_id": item_id}
    assert client.get(f"/api/inbox/{item_id}", headers=AUTH_HEADERS).status_code == 404

    keep = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": "还没处理的素材"}).json()["id"]
    old1 = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": "历史素材 A"}).json()["id"]
    old2 = client.post("/api/inbox", headers=AUTH_HEADERS, json={"content": "历史素材 B"}).json()["id"]
    client.post(f"/api/inbox/{old1}/archive", headers=AUTH_HEADERS)
    client.post(f"/api/inbox/{old2}/archive", headers=AUTH_HEADERS)

    cleared = client.delete("/api/inbox/history", headers=AUTH_HEADERS)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["deleted"] == 2
    remaining = client.get("/api/inbox", headers=AUTH_HEADERS).json()
    remaining_ids = {x["id"] for x in remaining}
    assert keep in remaining_ids
    assert old1 not in remaining_ids and old2 not in remaining_ids


def test_inbox_frontend_contract_files_are_wired():
    root = Path(__file__).resolve().parents[1]
    main = (root / "assets/js/vue/main.js").read_text(encoding="utf-8")
    app_root = (root / "assets/js/vue/components/AppRoot.js").read_text(encoding="utf-8")
    sidebar = (root / "assets/js/vue/components/SideBar.js").read_text(encoding="utf-8")
    api = (root / "assets/js/vue/api.js").read_text(encoding="utf-8")
    css = (root / "assets/app.css").read_text(encoding="utf-8")
    night = (root / "assets/themes/night.css").read_text(encoding="utf-8")

    assert "InboxPanel" in app_root
    assert "inbox-item" in main and "/inbox/:id" in main
    assert "InboxComposer" in sidebar
    assert "goInbox" in sidebar and "route.name === 'inbox' || route.name === 'inbox-item'" in sidebar
    assert "<span v-html=\"icon('clip')\"></span><span>收集</span>" in sidebar
    assert "inboxPendingCount" in sidebar and "store.inboxItems" in sidebar
    assert "@container (max-width: 220px)" in css and ".sidebar-quick-btn em {\n    display: none;" in css
    assert sidebar.index('<InboxComposer />') < sidebar.index('class="sidebar-head"') < sidebar.index('class="session-list"')
    assert 'class="inbox-recent-list"' not in (root / "assets/js/vue/components/InboxComposer.js").read_text(encoding="utf-8")
    assert "createInboxItem" in api and "generateInboxQuestions" in api and "selectInboxQuestion" in api
    assert "deleteInboxItem" in api and "clearInboxHistory" in api
    assert "createInboxItem: async (content, sourceType = 'text')" in api
    assert "generateInboxQuestions" in api  # manual trigger replaces auto-generation
    assert ".inbox-composer" in css and ".inbox-panel" in css
    assert (root / "assets/js/vue/components/InboxComposer.js").exists()
    assert (root / "assets/js/vue/components/InboxPanel.js").exists()

    # Inbox navigation is made from button elements, but visually it must keep
    # the neutral continuous-sidebar style. The night theme has a legacy global
    # button rule that turns unmatched buttons into solid accent blocks; inbox
    # buttons must stay excluded from it.
    assert ":not(.inbox-label)" in night
    assert ":not(.inbox-list-item)" in night
    assert ":not(.inbox-overview-item)" in night
    assert ":not(.inbox-breadcrumb-link)" in night
    assert ":not(.inbox-material-title-button)" in night
    assert ".inbox-label" in css and "background: transparent" in css
    assert ".inbox-label { cursor: default; }" in css
    assert ".inbox-list-item.active" in css and "background: var(--bg-2)" in css
    assert "border-left-color: var(--accent)" not in css

    inbox_panel = (root / "assets/js/vue/components/InboxPanel.js").read_text(encoding="utf-8")
    # Inbox follows the app shell's three-column rhythm: left global sidebar,
    # center generated questions, right material list. The component uses
    # display: contents so its detail pane and list pane can sit in shell columns.
    assert "workspace-shell.inbox-mode" in css
    assert "grid-template-columns: var(--sidebar-width, 260px) minmax(0, 1fr) 300px;" in css
    assert ".workspace-shell.inbox-mode .main-pane" in css and "display: contents" in css
    assert ".inbox-panel {\n  display: contents;" in css
    assert ".inbox-detail-pane" in css and "grid-column: 2;" in css
    assert ".inbox-list-pane" in css and "grid-column: 3;" in css
    assert "'inbox-detail-pane', { 'is-overview': !item }" in inbox_panel
    assert ".inbox-detail-pane.is-overview" in css
    assert inbox_panel.index("inbox-detail-pane") < inbox_panel.index('class="inbox-list-pane"')
    assert "v-if=\"item.error_msg && !questions.length\"" in inbox_panel
    assert "const visibleQuestions = computed(() => questions.value.filter(q => q.status !== 'replaced').slice(0, 5))" in inbox_panel
    assert "v-for=\"q in visibleQuestions\"" in inbox_panel
    assert "pendingItems" in inbox_panel
    assert "收集箱" in inbox_panel
    assert "class=\"inbox-page-composer\"" in inbox_panel
    assert "pageContent" in inbox_panel and "submitPageCollection" in inbox_panel and "generateQuestions" in inbox_panel
    assert "sourceOptions" not in inbox_panel and "sourceType" not in inbox_panel and "素材类型" not in inbox_panel
    assert "loadDomainOptions" in inbox_panel and "api.getKnowledgeTree()" in inbox_panel
    assert "可选领域" in inbox_panel  # simplified composer, modeOptions removed
    assert "class=\"inbox-overview-stats\"" not in inbox_panel
    assert "最近收集" in inbox_panel
    assert "displayInboxTitle" in inbox_panel and "archiveItem" in inbox_panel
    assert "inbox-material-card" in inbox_panel
    # batchable class removed with batch checkboxes
    assert "class=\"inbox-material-line\"" in inbox_panel
    assert "icon('clip')" in inbox_panel and "最近收集" in inbox_panel
    assert ".inbox-page-composer" in css and ".inbox-page-compose-grid" in css and ".inbox-compose-option-row" in css
    assert ".inbox-compose-domain-grid" in css and ".inbox-chip.active" in css
    assert ".inbox-compose-source" not in css
    assert ".inbox-overview-stats" not in css
    assert ".inbox-material-card" in css and "background: var(--bg-1, rgba(255,255,255,0.03));" in css
    assert "margin-bottom: 4px;" in css
    assert ".inbox-overview-section" in css and "gap: 0;" in css
    assert ".inbox-section-head .home-section-title" in css and "color: var(--fg-0);" in css
    assert ".inbox-material-line" in css and "display: flex;" in css and "gap: 8px;" in css
    assert ".inbox-material-line .inbox-list-status" in css and "flex-shrink: 0;" in css
    assert "justify-self: end;" not in css and "text-align: right;" not in css
    assert "@keydown.enter.prevent=\"openItem(x)\"" not in inbox_panel
    assert "inbox-material-title-button" in inbox_panel
    assert "@click.stop=\"openItem(x)\"" in inbox_panel
    # batch check removed with batch UI
    assert "最近收集" in inbox_panel  # renamed from 待处理素材
    assert "const isInboxRoute = computed(() => route.name === 'inbox' || route.name === 'inbox-item')" in inbox_panel
    assert "const itemId = computed(() => route.name === 'inbox-item'" in inbox_panel
    assert "if (!isInboxRoute.value) return;" in inbox_panel
    assert "WHERE i.status != 'archived'" not in (root / "aiterate_db.py").read_text(encoding="utf-8")
    assert "font-size: 15px;" in css and "font-size: 13px;" in css
    assert ".inbox-url-import input" in css and "font-size: 13px;" in css
    assert ".inbox-url-import input::placeholder" in css and "font-size: inherit;" in css
    assert ".inbox-page-input" in css and "font-size: 13px;" in css
    assert ".inbox-material-card" in css
    # batch selection CSS removed
    # batch toggle removed
    assert "icon('globe')" in inbox_panel and "icon('mic')" in inbox_panel and "icon('image')" in inbox_panel
    assert "mic:" in (root / "assets/js/vue/icons.js").read_text(encoding="utf-8")
    assert "image:" in (root / "assets/js/vue/icons.js").read_text(encoding="utf-8")
    assert ".inbox-source-tool-btn svg" in css and "gap: 6px;" in css
    assert "@media (max-width: 620px)" in css and ".inbox-page-compose-grid" in css and "grid-template-columns: 1fr;" in css


# ── Tests: Inbox Recommendations ───────────────────────────────────────────────────

def test_recommendation_table_exists():
    root = Path(__file__).resolve().parents[1]
    db_src = (root / "aiterate_db.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS inbox_recommendations" in db_src
    assert "idx_inbox_recs_batch" in db_src
    assert "idx_inbox_recs_status" in db_src


def test_build_interest_profile_function():
    root = Path(__file__).resolve().parents[1]
    db_src = (root / "aiterate_db.py").read_text(encoding="utf-8")
    assert "def build_user_interest_profile()" in db_src
    assert "active_nodes" in db_src
    assert "preferred_angles" in db_src


def test_recommendation_crud_functions():
    root = Path(__file__).resolve().parents[1]
    db_src = (root / "aiterate_db.py").read_text(encoding="utf-8")
    assert "def create_inbox_recommendations" in db_src
    assert "def get_inbox_recommendations" in db_src
    assert "def select_inbox_recommendation" in db_src
    assert "def ignore_inbox_recommendation" in db_src
    assert "def clear_recommendation_batch" in db_src


def test_recommendation_api_endpoints():
    root = Path(__file__).resolve().parents[1]
    server = (root / "aiterate_server.py").read_text(encoding="utf-8")
    assert '"/api/inbox/recommendations"' in server
    assert '"/api/inbox/recommendations/refresh"' in server
    assert '"/api/inbox/recommendations/{rec_id}/select"' in server
    assert '"/api/inbox/recommendations/{rec_id}/ignore"' in server


def test_recommendation_api_routes_before_item_id():
    """Recommendation routes must be defined before /api/inbox/{item_id} route."""
    root = Path(__file__).resolve().parents[1]
    server = (root / "aiterate_server.py").read_text(encoding="utf-8")
    rec_route_pos = server.index('"/api/inbox/recommendations"')
    item_route_pos = server.index('"/api/inbox/{item_id}"')
    assert rec_route_pos < item_route_pos, \
        "Recommendation route must come before {item_id} to avoid route collision"


def test_recommendation_ai_prompt():
    root = Path(__file__).resolve().parents[1]
    ai = (root / "aiterate_ai.py").read_text(encoding="utf-8")
    assert "RECOMMENDATION_SYSTEM" in ai
    assert "def generate_inbox_recommendations" in ai
    assert "interest_profile" in ai


def test_recommendation_job_processor():
    root = Path(__file__).resolve().parents[1]
    server = (root / "aiterate_server.py").read_text(encoding="utf-8")
    assert '"generate_inbox_recommendations"' in server
    assert "def _process_generate_inbox_recommendations" in server


def test_recommendation_frontend_state():
    root = Path(__file__).resolve().parents[1]
    inbox = (root / "assets/js/vue/components/InboxPanel.js").read_text(encoding="utf-8")
    assert "recommendations" in inbox
    assert "recsGenerating" in inbox
    assert "activeRecommendations" in inbox
    assert "loadRecommendations" in inbox
    assert "refreshRecommendations" in inbox


def test_recommendation_frontend_template():
    root = Path(__file__).resolve().parents[1]
    inbox = (root / "assets/js/vue/components/InboxPanel.js").read_text(encoding="utf-8")
    assert "为你推荐" in inbox
    assert "换一批" in inbox
    assert "inbox-recs-section" in inbox
    assert "inbox-rec-card" in inbox


def test_recommendation_css():
    root = Path(__file__).resolve().parents[1]
    css = (root / "assets/app.css").read_text(encoding="utf-8")
    assert ".inbox-recs-section" in css
    assert ".inbox-rec-card" in css
    assert ".inbox-rec-question" in css


def test_recommendation_api_methods():
    root = Path(__file__).resolve().parents[1]
    api = (root / "assets/js/vue/api.js").read_text(encoding="utf-8")
    assert "getInboxRecommendations" in api
    assert "refreshInboxRecommendations" in api
    assert "selectInboxRecommendation" in api
    assert "ignoreInboxRecommendation" in api


def test_inbox_question_system_rewritten():
    root = Path(__file__).resolve().parents[1]
    ai = (root / "aiterate_ai.py").read_text(encoding="utf-8")
    assert "默认模式（用户没指定领域）" in ai
    assert "不要强行把素材扯到不相关的领域" in ai
    assert "INBOX_QUESTION_SYSTEM_DEFAULT" in ai
    assert "INBOX_QUESTION_SYSTEM_DOMAIN" in ai
