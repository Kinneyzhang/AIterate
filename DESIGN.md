# AIIterate 设计文档

> 面向维护者的系统设计说明：目标、架构、状态机、数据模型、安全边界、测试策略和演进约束。

AIIterate 的设计重点不是“让 AI 回答得更长”，而是把学习行为固化成可验证、可追踪、可复习的状态机。系统中的每个模块都围绕一个问题展开：用户是否真的掌握了这个知识点？

## 1. 设计目标

### 1.1 产品目标

AIIterate 要解决四类学习问题：

1. 看 AI 回答时觉得懂了，过一会儿却讲不出来。
2. 学习过程没有状态，无法知道某个主题到底完成到哪里。
3. 薄弱点只存在于一次对话里，没有长期追踪。
4. 学完没有复习，知识无法进入长期记忆。

因此系统选择“学习状态机 + 认知资产账本”的设计：

```text
问题 / 观点
  → 学习材料
  → 主动复述
  → AI 评价
  → 薄弱点账本
  → 费曼检验
  → 复习排期
  → 知识树掌握度
```

### 1.2 工程目标

- 状态可解释：每个 session 必须处在明确状态中。
- 失败可恢复：后台 job 失败要有 error_msg 和 retry/recover 路径。
- 数据可审计：AI 评价、费曼报告、gaps、复习记录都要持久化。
- 测试可重复：默认测试不依赖真实 LLM、真实服务或生产数据库。
- 安全不侥幸：密钥只存设置，不在文档、HTML 静态文件或 API 响应中泄露明文。

## 2. 总体架构

```text
Browser: Vue 3 + Vue Router + Vite
  │
  │ HTTP JSON
  │ Auth: HttpOnly cookie or X-Admin-Token
  ▼
FastAPI: aiterate_server.py
  ├─ Auth APIs
  ├─ Settings / Profile / DB config APIs
  ├─ Session lifecycle APIs
  ├─ Deepen / Feynman / Review APIs
  ├─ Knowledge tree / Command center APIs
  ├─ Maintenance / Invariant APIs
  └─ DB-backed background job worker
      │
      ├── aiterate_db.py
      │     ├─ SQLAlchemy Core
      │     ├─ schema bootstrap and migration
      │     ├─ PostgreSQL production branch
      │     ├─ SQLite isolated test branch
      │     ├─ learning gaps / review / jobs / rubrics
      │     └─ invariant check and repair
      │
      └── aiterate_ai.py
            ├─ OpenAI-compatible provider routing
            ├─ role-based model config
            ├─ Tavily search injection
            ├─ prompt templates
            └─ robust JSON extraction with parse_failed markers
```

关键取舍：

- 路由层只做认证、参数校验、状态校验和业务编排。
- DB 层统一处理 SQL、方言差异、schema 演进和数据聚合。
- AI 层统一处理 provider/model、prompt、联网搜索和 JSON fallback。
- 前端只通过 API 操作状态，不直接推导服务端业务规则。

## 3. 后端模块职责

### 3.1 `aiterate_server.py`

职责：

- 创建 FastAPI app。
- 处理登录、登出、认证状态。
- 暴露 session、deepen、feynman、review、settings、knowledge tree、maintenance API。
- 实现状态机入口 guard。
- 启动 DB-backed job worker。
- 将多个 DB 查询聚合成 workspace payload。

设计原则：

- API handler 不直接拼复杂 SQL。
- 状态变更前先检查当前 status。
- 对外错误要明确，不能静默 fallback。
- 真实 LLM 调用不应长时间阻塞创建 session 请求。

### 3.2 `aiterate_db.py`

职责：

- 读取数据库配置并创建 SQLAlchemy engine。
- 初始化 schema 和轻量迁移。
- 提供 session、round、gap、review、job、profile、rubric 等 CRUD。
- 封装 PostgreSQL 与 SQLite 差异。
- 提供 command center、knowledge mastery、weekly report 等聚合数据。
- 提供 invariant 检查和可修复项 repair。

重要约定：

- 生产主路径是 PostgreSQL。
- 测试主路径是临时 SQLite。
- JSON 字段在 PostgreSQL 使用 JSONB，在 SQLite 使用 TEXT。
- 动态 update 必须走字段白名单。
- PostgreSQL 类型转换用 `CAST(:value AS jsonb)`，避免 SQLAlchemy 把 `::jsonb` 误识别成参数。
- 切换 DB 或测试候选配置后必须 dispose 临时 engine。

### 3.3 `aiterate_ai.py`

职责：

- 解析 settings 中的 LLM 配置。
- 按 role 选择 provider/base_url/api_key/model。
- 生成标题、初始回答、理解评价、追问回答、费曼题、费曼评分、复习评分。
- 处理 Tavily 搜索与搜索结果注入。
- 从 LLM 噪声输出中提取 JSON。

重要约定：

- LLM 配置只读 DB settings，不从环境变量兜底。
- `generate_initial_answer()` 返回 dict，调用方必须取 `result["answer"]`。
- JSON 解析失败必须显式返回 `parse_failed: true` 或等价标记。
- `_extract_json_block()` 必须能处理嵌套对象、字符串内花括号、转义字符、坏 JSON 后继续扫描。
- aiohttp ClientSession 应复用，并在应用 shutdown 时关闭。

## 4. 前端架构

当前前端主路径是 Vue 3 模块：

```text
assets/js/vue/
  main.js                         # createApp / router 初始化
  store.js                        # 全局响应式状态与派发方法
  api.js                          # fetch 封装、认证错误处理、API 方法
  icons.js                        # inline SVG 图标
  components/
    AppRoot.js                    # 根布局、登录态、overlay 路由
    SideBar.js                    # session 列表与全局统计
    TopBar.js                     # 顶部动作区
    Workspace.js                  # 学习、深化、费曼、复习主界面
    modals/
      LoginModal.js
      NewSessionModal.js
      SettingsModal.js
      KnowledgeTreeModal.js
      CommandCenterModal.js
```

前端原则：

- 所有请求走 `api.js`，避免裸 fetch 绕过认证处理。
- 401 统一触发 unauthorized 事件，由 AppRoot 接管登录态。
- 未认证时不加载业务数据。
- route overlay 不能破坏背景 session tab。
- 动态 Markdown 必须经过安全渲染。
- 用户输入进入 HTML 前必须 escape。
- 暗色和亮色主题共享结构，只改 token，不分裂成两套 UI。

构建约束：

```bash
cd ~/.hermes/workspace/aiterate
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 24
npx vite build
systemctl --user restart aiterate.service
```

Vite 8 需要 Node.js `>=20.19`，当前环境推荐 Node 24。

## 5. 数据模型

### 5.1 `sessions`

一个 session 代表一个学习主题。

核心字段：

- `id`：主键。
- `title`：AI 生成标题。
- `content`：用户原始问题或观点。
- `type`：`question` 或 `viewpoint`。
- `status`：状态机当前状态。
- `material`：AI 初始学习材料。
- `score`：最终或最近关键评分。
- `review_report`：费曼完成后的总结 JSON。
- `knowledge_node_id`：绑定知识树节点。
- `web_search`：是否开启联网搜索。
- `error_msg`：进入 error 时的错误说明。
- `created_at` / `updated_at`：审计时间。

### 5.2 `rounds`

round 表示一次学习交互或费曼题。

类型：

- `take`：用户写理解，AI 评价。
- `press`：用户追问，AI 回答。
- `feynman`：费曼题。每题一条 round，用 `group_id` 绑定同一题组。

核心字段：

- `session_id`：所属 session。
- `seq`：session 内顺序。
- `input`：用户输入或题目。
- `output`：AI 输出或用户答案。
- `eval_json`：评价 JSON。
- `score`：评分。
- `group_id`：费曼题组。
- `status`：pending/evaluated/completed 等。

### 5.3 `learning_gaps`

薄弱点账本。

来源：

- take 评价中的 `gaps`。
- 费曼失败的 `weak_points`。
- 复习低分或复习反馈中的薄弱点。

状态：

- `open`：待解决。
- `resolved`：已通过追问、复述或后续评价解决。
- `ignored`：用户或系统选择忽略。
- `reappeared`：曾解决但后续再次出现。

设计目标是让“我哪里不会”从一次性提示变成长期资产。

### 5.4 `review_schedule`

复习计划。

关键行为：

- 费曼通过或手动完成后创建 pending 复习。
- 到期复习在指挥中心展示。
- `submit` 会保存用户重新解释、AI 反馈和复习分数。
- 完成复习后自动创建下一轮复习。
- `skip` 只标记 skipped，不算 completed，不排下一轮。

### 5.5 `jobs`

后台任务队列。

当前主要任务：

```text
generate_session_answer
```

创建 session 后立即返回，后台 job 负责生成标题和学习材料。这样避免 HTTP 请求长时间等待 LLM。

job 需要支持：

- pending/running/completed/failed 状态。
- stuck running 恢复。
- 错误信息记录。
- 最大重试次数。
- worker 并发上限。

### 5.6 `profile` 与 settings

`profile.settings` 保存系统设置，包括：

- `admin_token`。
- `llm` provider/base_url/model/api_key/roles。
- `tavily_api_key`。
- `feynman_pass_score`。

读取设置时必须掩码 API key。更新时：

- 空字符串表示保留旧 key。
- 非空字符串表示覆盖 key。
- `__CLEAR__` 表示清除 key。

## 6. 状态机

### 6.1 状态图

```text
preparing → learning → deepening → feynman → completed
                            ↑          ↓
                            └─ revising
error 可由后台 job 或 AI 调用失败进入
```

状态含义：

- `preparing`：session 已创建，等待后台生成学习材料。
- `learning`：材料已生成，用户可以开始学习。
- `deepening`：用户已写理解或追问。
- `feynman`：存在待提交费曼题组。
- `revising`：费曼未通过，需要修正。
- `completed`：学习完成并进入复习队列。
- `error`：后台任务、AI 调用或数据异常。

### 6.2 入口 guard

- `deepen`：允许 `learning/deepening/revising`。
- `start-feynman`：允许 `deepening/revising`，且至少存在一次 `take`。
- `complete-feynman`：允许 `feynman`。
- `complete`：允许 `learning/deepening/revising`。
- `reopen`：允许 `completed/revising`。

非法入口返回 `409 Conflict`。

### 6.3 幂等与一致性

`start-feynman` 必须先检查是否已有 pending group。如果已有，直接返回旧 group，并标记复用，避免重复创建题组。

状态机 invariant 用于发现历史数据或异常中断造成的不一致，例如：

- 有 pending feynman rounds，但 session 不在 `feynman`。
- completed session 有 feynman rounds，但没有 `review_report`。
- error session 没有 `error_msg`。
- 同一个 session 有多个 pending feynman groups。
- 同一个 session 有多个 pending review schedules。
- preparing 太久未完成。
- completed 但分数异常为 0。

可安全修复的问题由 `repair_invariants()` 处理；不可确定的问题只报告，不静默修改。

## 7. 学习闭环

### 7.1 创建 session

```text
POST /api/sessions
  → db.create_session(status=preparing)
  → db.create_job(generate_session_answer)
  → worker claim job
  → ai.generate_title + ai.generate_initial_answer
  → update session title/material/status=learning
```

失败时：

- job 标记 failed 或重试。
- session 可进入 error。
- error_msg 保留原始错误摘要。

### 7.2 深化：take

用户写理解：

```text
POST /api/sessions/{id}/deepen
body: {"action_type": "take", "content": "..."}
```

后端行为：

- 校验状态。
- 调用 `evaluate_user_take()`。
- 写入 round。
- 将 gaps 写入 `learning_gaps`。
- 生成 suggested prompts。
- 更新 session 状态为 `deepening`。

### 7.3 深化：press

用户追问：

```text
POST /api/sessions/{id}/deepen
body: {"action_type": "press", "content": "..."}
```

后端行为：

- 校验状态。
- 调用 `answer_followup_question()`。
- 写入 round。
- 尝试根据追问内容解决已有 gaps。
- 保持或更新 session 状态为 `deepening`。

### 7.4 费曼

```text
POST /api/sessions/{id}/start-feynman
  → 校验状态和 take 轮次
  → 已有 pending group 则复用
  → 否则生成题目并写入 pending feynman rounds
  → session.status = feynman

POST /api/sessions/{id}/complete-feynman
  → 校验 status=feynman
  → 逐题评分
  → 保存 review_report
  → 通过：status=completed，排复习
  → 未通过：status=revising，生成 correction_plan，weak_points 回流 gaps
```

### 7.5 复习

复习入口：

- `GET /api/review/today`：到期复习列表。
- `POST /api/review/{id}/submit`：提交重新解释，由 AI 评价。
- `POST /api/review/{id}/skip`：跳过，不算完成。
- `POST /api/review/{id}/complete`：旧式直接完成，保留兼容。

复习间隔基于艾宾浩斯曲线，并根据分数做难度调制。低分加速复习，高分延长间隔。

## 8. AI 设计

### 8.1 Role routing

settings 中的 `llm.roles` 允许按任务配置不同模型：

```json
{
  "roles": {
    "title": {"model": "deepseek-chat"},
    "answer": {"model": "deepseek-chat"},
    "evaluate": {"model": "deepseek-chat"},
    "review": {"model": "deepseek-chat"},
    "deepen": {"model": "deepseek-chat"}
  }
}
```

如果 role 未配置，则回落到默认 provider/base_url/model/api_key。

### 8.2 JSON 解析策略

LLM 输出可能包含解释文本、Markdown code fence、嵌套对象或坏 JSON。解析策略必须：

- 扫描第一个完整 JSON 对象。
- 正确处理字符串中的 `{}`。
- 正确处理转义字符。
- 如果前面对象解析失败，继续扫描后面的对象。
- 失败时返回 fallback，但标记 `parse_failed`。

禁止行为：

- 用 `raw.find("{")` + `raw.rfind("}")` 简单截取。
- 解析失败后返回默认分数但不标记。
- 将错误吞掉只在控制台打印。

### 8.3 Tavily 搜索

联网搜索只在用户明确开启时使用。搜索 query 应该尽量短，避免把大段引用或材料全文送进搜索，造成检索污染。

搜索结果进入 system prompt 时要清楚标注来源，AI 回答仍应围绕用户问题，而不是机械拼贴搜索摘要。

## 9. 安全设计

### 9.1 认证

认证路径：

- Web：`POST /api/auth/login` 校验 admin token，成功后设置 HttpOnly cookie。
- Script：通过 `X-Admin-Token` header 调用受保护 API。
- Status：`GET /api/auth/status` 检查当前请求认证状态。

除公开入口和 auth/health 以外，业务 API 默认需要 `_require_admin`。

### 9.2 密钥保护

- 文档和示例只能使用占位符。
- `config/db.json` 不提交。
- settings GET 只返回 key 掩码和 `has_api_key`。
- HTML 静态源文件不得写入真实 admin token。
- 日志中避免输出完整 API key、token、数据库密码。

### 9.3 前端 XSS

- Markdown 渲染使用 DOMPurify。
- DOMPurify 不存在时 fail-closed，只输出 escape 后文本。
- Vue 模板中任何用户输入必须 escape。
- inline SVG 只使用本地受控 icon。

### 9.4 SQL 安全

- 使用 SQLAlchemy 参数绑定。
- 动态字段更新必须白名单。
- 不拼接用户输入到 SQL 标识符位置。
- PostgreSQL JSONB 类型转换使用 `CAST()`。

## 10. 性能设计

主要性能点：

- 创建 session 后用 DB job 异步生成初始材料。
- worker 用 semaphore 控制并发 LLM 调用。
- aiohttp ClientSession 复用连接。
- 高频查询建立索引：rounds/session/type、review/status/date、gaps/session/status。
- Command Center 在后端聚合，避免前端多接口拼装。
- session list 默认 limit，避免一次拉取无限历史。

当前系统是个人学习系统，优先保证可维护性和状态正确性，而不是为多租户高并发过度设计。

## 11. 测试设计

默认测试必须：

- 不依赖 `aiterate.service` 是否运行。
- 不调用真实 LLM。
- 不读取或污染生产 PostgreSQL。
- 不依赖固定 ID 或历史数据量。

实现方式：

- `tests/app_fixture.py` 创建临时 SQLite。
- monkeypatch DB 配置和 AI 函数。
- fake AI 返回 deterministic 结果。
- 测试中同步 claim 和处理后台 job。
- 覆盖创建、深化、费曼通过、费曼失败回退、手动完成、复习、边界错误。

常用命令：

```bash
cd ~/.hermes/workspace/aiterate
~/.hermes/venv/bin/python -m pytest -q
~/.hermes/venv/bin/python -m pytest tests/test_full_flow_repeatable.py -q
~/.hermes/venv/bin/python -m pytest tests/test_api_contract.py tests/test_state_machine.py -q
```

真实服务冒烟脚本：

```bash
~/.hermes/venv/bin/python tests/live_full_flow.py
```

注意：真实冒烟会调用真实 LLM 并创建真实业务数据，运行前必须明确接受副作用，运行后按需清理。

## 12. 运维与维护

### 12.1 systemd

```bash
systemctl --user restart aiterate.service
systemctl --user status aiterate.service --no-pager
journalctl --user -u aiterate.service -f
```

### 12.2 健康检查

```bash
curl http://127.0.0.1:7070/healthz
```

认证 API 用 header：

```bash
curl -H "X-Admin-Token: $AITERATE_ADMIN_TOKEN" http://127.0.0.1:7070/api/ready
```

### 12.3 数据健康脚本

```bash
cd ~/.hermes/workspace/aiterate
~/.hermes/venv/bin/python - <<'PY'
import json
import aiterate_db as db
print(json.dumps({
  "stats": db.get_stats(),
  "system_health": db.get_system_health(),
  "job_counts": {
    "pending": db.get_pending_job_count(),
    "running": db.get_running_job_count(),
  },
  "invariants": db.check_invariants(),
}, ensure_ascii=False, default=str, indent=2))
PY
```

### 12.4 数据清理

清理生产业务数据前必须备份。若只清理学习历史，应保留 `profile`，避免丢失 admin token、LLM settings 和主题偏好。

推荐清理范围：

```text
sessions
rounds
review_schedule
learning_gaps
jobs
```

不要默认清理：

```text
profile
```

## 13. API 设计概览

公开或半公开入口：

- `GET /`：前端入口。
- `GET /favicon.svg`：图标。
- `GET /healthz`：健康检查。
- `POST /api/auth/login`：登录。
- `POST /api/auth/logout`：登出。
- `GET /api/auth/status`：认证状态。

核心业务 API：

```text
GET/PATCH /api/profile
GET/PATCH /api/settings
GET/PUT   /api/db-config
GET       /api/ready
GET       /api/stats
GET       /api/sessions
POST      /api/sessions
GET       /api/sessions/{id}
GET       /api/sessions/{id}/workspace
POST      /api/sessions/{id}/deepen
POST      /api/sessions/{id}/start-feynman
POST      /api/sessions/{id}/complete-feynman
POST      /api/sessions/{id}/complete
POST      /api/sessions/{id}/reopen
GET       /api/sessions/{id}/gaps
PATCH     /api/sessions/{id}/knowledge-node
POST      /api/sessions/{id}/suggest-knowledge-nodes
GET       /api/knowledge-tree
GET       /api/knowledge-tree/progress
GET       /api/knowledge-tree/sessions
GET       /api/knowledge-tree/mastery
GET       /api/knowledge-tree/recommend
GET       /api/review/today
POST      /api/review/{id}/submit
POST      /api/review/{id}/skip
POST      /api/review/{id}/complete
GET       /api/command-center
GET/PATCH /api/rubrics
GET       /api/jobs/status
GET       /api/maintenance/check-invariants
POST      /api/maintenance/repair-invariants
GET       /api/report/weekly
```

业务 API 默认需要管理员认证。

## 14. 变更规范

### 14.1 修改状态机

必须同步修改：

- `aiterate_server.py` guard。
- `aiterate_db.py` invariant 检查。
- 前端状态显示和可用按钮。
- `README.md` 状态机速览。
- `USER_GUIDE.md` 状态说明。
- `DESIGN.md` 状态机章节。
- 状态机测试。

### 14.2 修改 DB schema

必须同步修改：

- `init_db()` 建表或迁移。
- PostgreSQL 分支。
- SQLite 测试分支。
- 相关 fixture。
- 运维文档和数据模型说明。

新增列时不能只改 `CREATE TABLE IF NOT EXISTS`，因为已有表不会自动补列。应使用统一迁移函数。

### 14.3 修改前端

必须同步执行：

```bash
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 24
npx vite build
systemctl --user restart aiterate.service
```

必要时用浏览器验证：

- 登录流程。
- console errors。
- 移动端滚动。
- 暗亮主题。
- Command Center。
- Workspace 主流程。

### 14.4 修改 AI 输出结构

必须同步修改：

- prompt。
- 解析函数。
- fallback 结构。
- `parse_failed` 语义。
- tests 中 fake AI 输出。
- 前端展示逻辑。

禁止只改 prompt 不改解析和测试。

## 15. 文档规范

项目文档分工：

- `README.md`：项目入口。讲价值、快速开始、运行、测试、部署、API 概览和安全边界。
- `USER_GUIDE.md`：用户手册。讲日常怎么用、好坏示例、常见问题和推荐习惯。
- `DESIGN.md`：维护手册。讲架构、状态机、数据模型、测试、运维和变更规范。

文档要求：

- 命令必须可复制。
- 涉及副作用必须说明，例如真实冒烟测试会创建数据。
- 不能出现真实 secret。
- 状态名、API 路径、文件路径必须和代码一致。
- README 不堆过深实现细节，细节放 DESIGN。
- 用户操作细节放 USER_GUIDE，不放 DESIGN。
- 修改代码行为后同步更新对应文档。

## 16. 已知边界

- 当前定位是个人学习系统，不是公网多租户 SaaS。
- SQLite 是测试与轻量路径，生产主路径仍是 PostgreSQL。
- live 测试会污染真实业务数据，不能作为默认回归。
- 重复 session 标题不应强制折叠；那可能是用户有意重复练习或测试数据。
- 费曼失败率高不一定是 bug，可能说明答案缺机制、例子或边界。

## 17. 演进方向

优先级较高的方向：

- 更强的复习入口，让到期复习更难被忽略。
- correction plan 前端展示增强，让费曼失败后的下一步更明确。
- knowledge node 推荐更主动，在新建和未绑定 workspace 中都给出轻提示。
- weekly report 更好地总结掌握度、复习压力和重复 gaps。
- 更严格的备份与恢复流程文档。

非目标：

- 不为了“聊天自由度”破坏学习状态机。
- 不把默认测试改成依赖真实模型。
- 不在个人工具阶段过度引入多租户权限体系。
