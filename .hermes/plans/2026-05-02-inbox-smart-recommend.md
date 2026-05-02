# Inbox 智能推荐优化 Implementation Plan

> **For Hermes:** Implement task-by-task in order.

**Goal:** 降低收集箱心智负担 + 新增基于用户兴趣的智能推荐 feed

**Architecture:** 
- 素材问题：重写 INBOX_QUESTION_SYSTEM，默认模式聚焦 what/why/how（≤3 个不跨域）
- 智能推荐：新表 `inbox_recommendations`，懒加载按日批次生成，基于 session/gap 构建兴趣 profile 传给 AI
- 前端：InboxPanel 首页新增「为你推荐」区块

**Tech Stack:** FastAPI + SQLAlchemy Core + Vue 3 + PostgreSQL

---

### Task 1: DB — 新表 inbox_recommendations

**Files:** `aiterate_db.py`

Add `inbox_recommendations` table and CRUD functions.

### Task 2: DB — 用户兴趣 profile 构建函数

**Files:** `aiterate_db.py`

`build_user_interest_profile()` — 从 sessions + rounds + learning_gaps + knowledge_tree 实时构建。

### Task 3: AI — 重写 INBOX_QUESTION_SYSTEM（双模式）

**Files:** `aiterate_ai.py`

默认模式：what/why/how，域内聚焦。选了领域：领域内深化。生成 ≤4 个问题。

### Task 4: AI — 新增 RECOMMENDATION_SYSTEM + generate_inbox_recommendations()

**Files:** `aiterate_ai.py`

基于兴趣 profile 生成 4 个推荐问题。

### Task 5: Server — 推荐相关 endpoint + job type

**Files:** `aiterate_server.py`

新增 `GET /api/inbox/recommendations`、`POST refresh`、`POST select`、`POST ignore`。

### Task 6: Frontend — InboxPanel 推荐 feed

**Files:** `assets/js/vue/components/InboxPanel.js`

首页新增「为你推荐」区块，显示今日推荐问题。

### Task 7: CSS — 推荐卡片样式

**Files:** `assets/app.css`

### Task 8: 测试

**Files:** `tests/test_inbox_feature.py`

### Task 9: Vite build + restart + verify

---

**Verify:** `pytest -q` all pass, browser check inbox page, recommendation feed renders.
