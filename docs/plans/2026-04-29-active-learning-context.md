# Phase 17: Active Learning Context Implementation Plan

> **For Hermes:** Implement task-by-task with strict TDD. Do not add production code before a failing test.

**Goal:** Turn AIIterate from isolated learning sessions into an active learning context system: entries, threads, related context, learning collaborators, active briefs, provenance, and "What do I think about X?" synthesis.

**Architecture:** Keep AIIterate learning-first. Add a thin persistent context layer around existing Inbox/Sessions/Gaps/Reviews instead of replacing them. All AI or heuristic suggestions must include provenance. First implementation is a usable MVP: database + API + minimal front-end surfacing; no generic chatbot, no complex graph UI, no embedding dependency.

**Tech Stack:** FastAPI, SQLAlchemy Core, PostgreSQL production + SQLite isolated tests, Vue 3 ESM frontend, existing job queue and settings model.

---

## Scope Boundaries

Implement only these requested areas:

1. Inbox素材升级为 Entry
2. Thread 持续主题
3. 主动上下文推荐
4. 学习协作者 Agent（非聊天机器人）
7. 每日/每周主动简报
8. Provenance 来源追溯
9. “What do I think about X?” 查询

Explicitly out of scope for this phase:

- BuJo bridge
- Mounted Context
- E2E sync/offline app
- General MCP connector UI
- Publishing
- Full embedding/RAG pipeline
- Agents automatically modifying data without user confirmation

---

## Data Model MVP

### New tables

```sql
entries (
  id SERIAL PRIMARY KEY,
  title TEXT,
  content TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'note',
  source_type TEXT NOT NULL DEFAULT 'text',
  source_url TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)

threads (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'topic',
  summary TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)

thread_items (
  id SERIAL PRIMARY KEY,
  thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  item_type TEXT NOT NULL, -- entry/session/gap/review
  item_id INTEGER NOT NULL,
  relation TEXT NOT NULL DEFAULT 'related',
  confidence SMALLINT NOT NULL DEFAULT 80,
  provenance JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(thread_id, item_type, item_id, relation)
)

learning_agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'relevant', -- off/invoked/relevant/active
  goal TEXT NOT NULL,
  enabled SMALLINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)

agent_runs (
  id SERIAL PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES learning_agents(id),
  target_type TEXT NOT NULL,
  target_id INTEGER,
  trigger TEXT NOT NULL DEFAULT 'manual',
  output JSONB NOT NULL DEFAULT '{}',
  provenance JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

### Existing table migrations

```sql
ALTER TABLE inbox_items ADD COLUMN entry_id INTEGER REFERENCES entries(id) ON DELETE SET NULL;
ALTER TABLE inbox_questions ADD COLUMN provenance JSONB DEFAULT '{}';
ALTER TABLE sessions ADD COLUMN source_entry_id INTEGER REFERENCES entries(id) ON DELETE SET NULL;
ALTER TABLE sessions ADD COLUMN active_thread_id INTEGER REFERENCES threads(id) ON DELETE SET NULL;
```

SQLite test DB must get equivalent TEXT/INTEGER columns.

---

## API MVP

### Entries

- `GET /api/entries?limit=100&q=&kind=&status=`
- `POST /api/entries` body `{content, title?, kind?, source_type?, source_url?, metadata?}`
- `GET /api/entries/{id}`
- `PATCH /api/entries/{id}`
- Inbox creation must also create/link an Entry.
- Selecting an Inbox question must create a Session with `source_entry_id` and question provenance.

### Threads

- `GET /api/threads?limit=100`
- `POST /api/threads` body `{title, kind?, summary?, metadata?}`
- `GET /api/threads/{id}` includes `items`
- `POST /api/threads/{id}/items` body `{item_type, item_id, relation?, confidence?, provenance?}`
- `DELETE /api/threads/{id}/items/{thread_item_id}`
- `PATCH /api/sessions/{id}/thread` body `{thread_id|null}`

### Active Context + Provenance

- `GET /api/sessions/{id}/related-context`
  - Returns related entries/sessions/gaps/reviews/thread items.
  - Every item has `provenance: [{type, id, title, excerpt, reason}]`.
  - First version uses full-text-ish keyword scoring, not embeddings.

### Learning Collaborator Agents

- `GET /api/agents`
- `PATCH /api/agents/{id}` body `{mode?, enabled?, goal?}`
- `POST /api/agents/{id}/run` body `{target_type, target_id?, query?}`
- Built-ins:
  - `question_alchemist`
  - `context_detective`
  - `feynman_coach`
  - `review_scheduler`
  - `action_translator`
- First version is deterministic/heuristic using existing DB context; no new LLM prompt until the data contract stabilizes.

### Briefs

- `GET /api/briefs/learning?period=daily|weekly`
- Returns new entries, active sessions, due reviews, open gaps, suggested focus, with provenance.

### Synthesis

- `POST /api/me/synthesis` body `{query}`
- Returns:
  - `answer`: “我目前对 X 的理解”
  - `evidence`: sessions/entries/gaps/reviews with provenance
  - `gaps`: unresolved gaps related to query
  - `next_steps`: 2-5 suggestions

---

## Frontend MVP

1. ContextRail: add “相关上下文” card for current session.
2. Inbox detail: show linked Entry id/source; creation still feels like Inbox, but data is Entry-backed.
3. Session header/right rail: show active Thread and source Entry when available.
4. Add a simple “学习简报” overlay reachable from Command Center or topbar later; first version may be API-only if time is tight.
5. Add a lightweight synthesis input in Command Center or a new overlay: “我对 X 目前怎么理解？”
6. Do not add chat UI.

---

## TDD Task Sequence

### Task 1: RED tests for Entry-backed Inbox

**Files:**
- Test: `tests/test_active_learning_context.py`
- Modify later: `aiterate_db.py`, `aiterate_server.py`

Tests:
- `POST /api/inbox` creates an `entry_id` linked to `inbox_items`.
- `GET /api/entries` returns that entry.
- Selecting an inbox question creates a session with `source_entry_id`.
- Selected question includes provenance referencing entry + inbox question.

Run:
```bash
~/.hermes/venv/bin/python -m pytest tests/test_active_learning_context.py::test_inbox_creates_entry_and_selected_session_keeps_source_provenance -q -vv
```
Expected RED: missing table/API/fields.

### Task 2: GREEN Entry schema/API

Implement:
- `entries` table and migrations.
- DB helpers: `create_entry`, `get_entry`, `get_entries`, `update_entry`.
- `inbox_items.entry_id` migration.
- `POST /api/inbox` creates entry first, then inbox item.
- Entry API endpoints.

Verify target test passes.

### Task 3: RED tests for Threads

Tests:
- Create thread.
- Attach entry and session to thread.
- `GET /api/threads/{id}` returns ordered items with provenance.
- Patch session active thread.

Expected RED: endpoints missing.

### Task 4: GREEN Thread schema/API

Implement:
- `threads`, `thread_items` tables and indexes.
- DB helpers.
- API endpoints.
- `sessions.active_thread_id` migration.

### Task 5: RED tests for Related Context + Provenance

Tests:
- Create two related sessions/entries/gaps sharing keyword.
- `GET /api/sessions/{id}/related-context` returns related items.
- Every result has non-empty provenance with type/id/reason.

### Task 6: GREEN Related Context

Implement:
- `extract_keywords(text)` simple tokenizer for Chinese/English-ish text.
- `find_related_context_for_session(session_id, limit=8)`.
- API endpoint.
- Include thread items if session has `active_thread_id`.

### Task 7: RED tests for Learning Agents

Tests:
- Built-in agents are seeded idempotently.
- `GET /api/agents` returns five collaborators.
- Running `context_detective` on a session returns suggestions with provenance.
- Disabled agents cannot run.

### Task 8: GREEN Learning Agents

Implement:
- `learning_agents`, `agent_runs` tables.
- Seed built-ins in `init_db()`.
- DB helpers + API endpoints.
- Deterministic agent output based on related context/gaps/reviews.

### Task 9: RED tests for Learning Briefs

Tests:
- Daily brief returns new entries, active sessions, due reviews, open gaps.
- Every suggested focus item has provenance.
- Weekly brief uses wider time window.

### Task 10: GREEN Briefs

Implement:
- `build_learning_brief(period)` helper.
- `/api/briefs/learning` endpoint.
- No cron yet; API first.

### Task 11: RED tests for “What do I think about X?”

Tests:
- Query “MVCC” synthesizes from sessions/entries/gaps.
- Response includes answer, evidence, gaps, next_steps, provenance.
- Empty query 422.

### Task 12: GREEN Synthesis

Implement:
- `synthesize_personal_understanding(query)` heuristic MVP.
- Endpoint `/api/me/synthesis`.
- Reuse related context/provenance utilities.

### Task 13: Frontend minimal integration tests

Add static tests:
- ContextRail imports/calls `getRelatedContext`.
- API includes entries/threads/agents/brief/synthesis methods.
- No native `alert/confirm/prompt`.

### Task 14: Frontend minimal UI

Implement:
- ContextRail related context card.
- Entry/source/thread badges in Workspace/Inbox where available.
- Synthesis panel in Command Center or lightweight modal.

### Task 15: Full verification

Run:
```bash
cd ~/vibe/aiterate
~/.hermes/venv/bin/python -m pytest -q
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 24 && npx vite build
systemctl --user restart aiterate.service
curl -sS http://127.0.0.1:7070/healthz
```

Browser verify:
- Inbox creation still works.
- Entry API reflects Inbox input.
- Session shows related context.
- Synthesis query returns useful result.
- Console has no JS errors.

### Task 16: Commit/push

Commit in meaningful checkpoints if implementation grows too large:

```bash
git add ...
git commit -m "Add active learning context foundation"
git push origin main
```

---

## Acceptance Criteria

- Existing Inbox/session/learning flows remain backward compatible.
- Every new suggestion/agent/brief/synthesis result includes provenance.
- No LLM required for tests.
- SQLite isolated test suite passes.
- PostgreSQL production migration succeeds on service restart.
- Frontend build passes.
- Browser console has no JS errors.

---

## Implementation Notes

- Prefer append-only provenance JSON over opaque strings.
- Do not delete existing inbox tables; Entry backs them.
- Do not auto-create huge numbers of threads. MVP creates manual threads and suggests related context.
- Agents are collaborators/actions, not chat. No chat transcript table in this phase.
- Keep all DB helpers in `aiterate_db.py` for now to match existing project style; refactor later only if needed.
