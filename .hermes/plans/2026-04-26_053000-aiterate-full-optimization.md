# AIIterate 全量优化方案

**生成时间**: 2026-04-26  
**基线数据**: 78 sessions, 217 rounds, 39 reviews, 21 parse failures, gap ledger 为空  
**测试**: 50 unit + 10 state machine 全部通过 ✅

---

## 依赖关系图

```
P0-1 parse 修复 ──→ P0-1b gap ledger 激活 ──→ P1-5 suggestions 生效
                    ──→ P2-9  parse_failed 一致化
P0-3 auth 竞态    (独立)
P1-4 review_report 修复 (独立, DB repair)
P2-10 DB index    (独立)
P1-7 CC 增强       (独立)
P1-6 知识节点推荐  (独立)
P2-8  aiohttp     (独立)
```

共 10 项优化，预计 6~8 轮修改。

---

## P0-1 🔴 修复 AI JSON 解析 → 连锁激活 gap ledger

**现状**: `_extract_json_block` 用 `raw.find("{")` + `raw.rfind("}")` → 嵌套 JSON 或多段文本时找错闭合 → 21 次解析失败 → gaps 永远空数组 → gap ledger 为空

**涉及文件**: `aiterate_ai.py:11-16`

**方案**: 用 balance 括号匹配替代 find/rfind：

```python
def _extract_json_block(raw: str) -> dict | None:
    """从 AI 原始输出中提取第一个完整 JSON 对象（处理嵌套/多段文本）"""
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None
```

**改法**:
1. 替换 `_extract_json_block` 函数（行 11-16）
2. 更新三处调用:
   - `evaluate_user_take` 行 268: `block = _extract_json_block(raw)` → 返回 dict 或 None
   - `generate_review_questions` 行 368: 同上
   - `suggest_deepen_prompts` 行 407: 同上
   - `evaluate_review_answers` 行 464: 同上

**效果**: parse 失败率预期从 27% → <5%

**验证**:
```bash
cd ~/.hermes/workspace/aiterate
~/.hermes/venv/bin/python -m pytest tests/test_unit.py tests/test_state_machine.py -q
# 再跑 live 测试确认 AI round 正常
~/.hermes/venv/bin/python tests/live_full_flow.py
```

---

## P0-1b 🟠 修复后 gap ledger 自动激活

**现状**: `create_gaps_from_take` 已正确实现，但输入 `eval_json["gaps"]` 始终为空

**无需改代码** — P0-1 修复后 parse 成功 → gaps 非空 → `create_gaps_from_take` 正常插入 → gap ledger 开始有数据

**验证**: P0-1 完成后跑一轮 take → `SELECT COUNT(*) FROM learning_gaps` 应有 >0

---

## P0-3 🔴 修复前端 auth 竞态

**证据**: 浏览器 console: `Failed to load sessions: Missing or invalid admin token`  
**根因**: `SideBar.js onMounted` 用裸 `fetch('/api/stats')` 请求数据，此时 cookie 可能还没设置（api.js 的 401 拦截只对 `request()` 函数有效，裸 fetch 不经过它）

**涉及文件**: `assets/js/vue/components/SideBar.js:36-41`

**改法**: SideBar 的 `loadGlobalStats()` 改用 `api` 封装：

```js
// SideBar.js line 36-41: 把裸 fetch 改成 api 调用
async function loadGlobalStats() {
  try {
    globalStats.value = await api.getSessions().then(sessions => ({
      total_sessions: sessions.length,
      completed_sessions: sessions.filter(s => s.status === 'completed').length,
    }));
  } catch (_) { /* fallback to list stats */ }
}
```

或者更直接——给 api.js 加 `getStats`:
```js
// api.js
getStats: () => request('/api/stats'),
```

然后 SideBar 调用 `api.getStats()`。

**验证**: 登录后浏览器 console 无 `Failed to load sessions` 错误

---

## P1-4 🟠 修复 5 个 missing review_report

**现状**: `check_invariants` 报 session [21, 22, 27, 28, 32] 有 feynman rounds 但 review_report 为 NULL

**方案**: 在 `repair_invariants()` 中加修复逻辑 — 从已完成 feynman rounds 的 eval_json 重建 review_report

**涉及文件**: `aiterate_db.py` `repair_invariants()` 函数

**改法**: 在 `repair_invariants` 末尾新增：
```python
# Fix completed sessions with feynman rounds but no review_report
broken = _fetch_all("""
    SELECT DISTINCT s.id FROM sessions s
    JOIN rounds r ON r.session_id = s.id
    WHERE s.status = 'completed'
      AND r.type = 'feynman' AND r.status = 'completed'
      AND s.review_report IS NULL
""")
for row in broken:
    # 从最近完成的 feynman group 重建 report
    rounds = _fetch_all("""
        SELECT * FROM rounds WHERE session_id = :sid AND type = 'feynman'
        AND status = 'completed' ORDER BY seq ASC
    """, {"sid": row["id"]})
    if rounds:
        report = {
            "final_score": rounds[-1].get("score", 0),
            "mastery_level": "理解",
            "strong_points": [],
            "weak_points": [],
            "final_summary": f"Auto-repaired: {len(rounds)} rounds completed",
            "passed": True,
            "pass_score": 60,
            "parse_failed": False,
            "repaired": True,
        }
        save_review_report(row["id"], report)
    repaired += 1
```

**验证**:
```bash
curl -s -X POST "http://192.168.31.222:7070/api/maintenance/repair-invariants?dry_run=false"
# 再查 invariants → completed_missing_review_report 应为 0
```

---

## P2-10 🟡 添加数据库索引

**涉及文件**: `aiterate_db.py` `init_db()` 函数

**改法**: 在 `init_db()` 的 `with get_engine().begin() as conn:` 块末尾追加：

```python
# Phase 5.3: Performance indexes
_ensure_index(conn, "rounds", "idx_rounds_session_type", ["session_id", "type"])
_ensure_index(conn, "review_schedule", "idx_review_status_date", ["status", "review_date"])
_ensure_index(conn, "learning_gaps", "idx_gaps_session_status", ["session_id", "status"])
```

需新增辅助函数：
```python
def _ensure_index(conn, table, index_name, columns):
    """创建索引（如果不存在）。兼容 SQLite 和 PostgreSQL。"""
    cols = ", ".join(columns)
    if _is_sqlite():
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({cols})"))
    else:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({cols})"))
```

**验证**: 重启服务 → 查 DB 索引：
```sql
SELECT indexname FROM pg_indexes WHERE tablename IN ('rounds','review_schedule','learning_gaps');
```

---

## P1-7 🟠 Command Center 增强

### 7a. 修复 limit=10 硬编码

**涉及文件**: `aiterate_db.py:1881` `get_today_reviews(limit=20)` → 改为 limit=50

```python
def get_today_reviews(limit: int = 50) -> list[dict]:
```

### 7b. 重复 session 标题提示

**问题**: 用户创建了 9 个"布隆过滤器原理与场景"session → CC 里大量重复条目

**方案**: CC 前端加去重提示——如果同一标题有 ≥2 个 session，显示 "还有 N 个同名 session"

**涉及文件**: `assets/js/vue/components/modals/CommandCenterModal.js`

**改法**: 渲染 review_due 列表时 group by title，多个同 title 条目折叠为一条 + 展开按钮

### 7c. 评分 badge 覆盖全部 review 条目

**问题**: 部分 review 条目不显示分数（因为 `sessions.score` 只在费曼完成后写入）

**方案**: `get_today_reviews` SQL 用 COALESCE 取 session.score 或最新 feynman final_score：

```sql
SELECT rs.id AS review_id, ..., 
       COALESCE(s.score, 
         (SELECT r.score FROM rounds r WHERE r.session_id = rs.session_id 
          AND r.type = 'feynman' AND r.status = 'completed' 
          ORDER BY r.seq DESC LIMIT 1), 0) AS display_score
FROM review_schedule rs ...
```

**验证**: CC 所有 review 条目都有分数显示，重复标题折叠

---

## P1-6 🟠 知识节点推荐增强

**现状**: 55/78 sessions 未绑定知识节点 → 知识树无法有效追踪

**方案**: Workspace 顶部加一个显眼的绑定提示，对未绑定 session 展示推荐节点按钮

**涉及文件**: `assets/js/vue/components/Workspace.js` (template 部分)

**改法**:
1. 检查 `store.workspace.knowledge_node_id` 为 null 时
2. 显示一行提示: "📌 未绑定知识节点 — [查看推荐]"
3. 点击调用 `api.getRecommendedNodes()` 展示弹窗

```js
// Workspace.js setup() 中加
const showNodeSuggestion = computed(() => 
  store.workspace && !store.workspace.knowledge_node_id
);
```

**验证**: 打开一个无 knowledge_node_id 的 session → 应看到绑定提示

---

## P2-9 🟡 parse_failed 一致性修复

**涉及文件**: `aiterate_ai.py:371-372`

**改法**: `generate_review_questions` parse 失败时标记 `parse_failed`:

```python
except Exception:
    return {"questions": ["用自己的话解释这个概念的核心是什么？"],
            "parse_failed": True}
```

**涉及文件**: 还有 `generate_initial_answer` 和 `answer_followup_question` 不需改（它们不返回 JSON），`suggest_deepen_prompts` 的 fallback 返回空 `suggestions` 也不需特殊标记

**验证**: 同 P0-1

---

## P2-8 🟡 aiohttp session 复用

**涉及文件**: `aiterate_ai.py:60-122`

**改法**: 模块级创建单例 session，startup 时初始化，shutdown 时关闭：

```python
# 模块顶部加
_http_session: aiohttp.ClientSession | None = None

async def _get_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=90)
        )
    return _http_session

async def close_http_session():
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
```

然后三处 `async with aiohttp.ClientSession(...) as session:` 改为 `session = await _get_session()`

**`aiterate_server.py` startup/shutdown 加**:
```python
@app.on_event("shutdown")
async def shutdown():
    await ai.close_http_session()
```

**验证**: 压测 10 个请求 → 连接复用，无 `Unclosed client session` 警告

---

## 🧪 回归测试

每轮修改后：

```bash
# 1. 离线测试（必须全绿）
cd ~/.hermes/workspace/aiterate
~/.hermes/venv/bin/python -m pytest tests/test_unit.py tests/test_state_machine.py -q

# 2. 重启服务
systemctl --user restart aiterate.service

# 3. API 可用性
curl http://192.168.31.222:7070/healthz

# 4. 不变式检查
curl -s http://192.168.31.222:7070/api/maintenance/check-invariants | python3 -m json.tool

# 5. 浏览器手动验证（登录 → 点 CC → 选 session → deepen → feynman）

# 6. Live 回归（改完 P0-1 后必跑）
~/.hermes/venv/bin/python tests/live_full_flow.py
```

---

## 📋 执行顺序清单

| # | 优化项 | 预估改动行数 | 风险 | 依赖 |
|---|--------|-------------|------|------|
| 1 | P0-1 JSON parse 修复 | ~20 行 | 中（核心路径） | 无 |
| 2 | P2-9 parse_failed 一致化 | 1 行 | 低 | 无 |
| 3 | P0-3 auth 竞态修复 | ~5 行 | 低 | 无 |
| 4 | P2-10 加 DB index | ~15 行 | 低 | 无 |
| 5 | P1-4 review_report 修复 | ~30 行 | 低 | 无 |
| 6 | P1-7a CC limit 增大 | 1 行 | 低 | 无 |
| 7 | P1-7c review 评分 badge | ~10 行 SQL | 低 | 无 |
| 8 | P1-7b 重复 session 折叠 | ~30 行 JS | 低 | 7c |
| 9 | P1-6 知识节点推荐 | ~15 行 | 低 | 无 |
| 10 | P2-8 aiohttp 复用 | ~30 行 | 低 | 无 |

每次修改后跑 `pytest` + `Vite build` + `systemctl restart`。
