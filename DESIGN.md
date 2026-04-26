# AIIterate 设计文档

## 1. 设计目标

AIIterate 的核心目标不是“聊天”，而是把学习过程固化成可重复的状态机：

1. 把一个问题转化为结构化学习材料。
2. 让用户主动复述、追问、修正。
3. 通过费曼检验确认是否真正掌握。
4. 将薄弱点、复习计划、知识树进度沉淀下来。
5. 用指挥中心持续提醒下一步最该做什么。

系统强调：可追踪、可复习、可修正、可验证。

## 2. 总体架构

```text
Browser(Vue 3 + Vite)
  │
  │ HTTP + Cookie/Header Auth
  ▼
FastAPI aiterate_server.py
  ├─ Auth / Settings / Sessions / Review / Maintenance APIs
  ├─ Background job worker
  ├─ State transition guards
  └─ Workspace aggregation
  │
  ├── aiterate_db.py
  │     ├─ SQLAlchemy Core
  │     ├─ schema migration
  │     ├─ PostgreSQL production branch
  │     ├─ SQLite test branch
  │     └─ invariant repair/check
  │
  └── aiterate_ai.py
        ├─ provider/model routing
        ├─ role-based prompts
        ├─ Tavily search
        └─ robust JSON extraction
```

## 3. 模块职责

### 3.1 `aiterate_server.py`

负责：

- FastAPI app 初始化。
- 登录、登出、认证状态。
- Session 生命周期 API。
- 深化、费曼、复习、指挥中心、知识树 API。
- DB-backed job worker：异步生成 session 初始回答。
- 状态机入口 guard。
- workspace 聚合 payload。

原则：

- 路由层只做鉴权、参数校验、状态校验、业务编排。
- 数据读写下沉到 `aiterate_db.py`。
- AI 调用下沉到 `aiterate_ai.py`。
- 不在路由里拼接临时 SQL。

### 3.2 `aiterate_db.py`

负责：

- 数据库配置读取和 engine 管理。
- Schema 创建与轻量迁移。
- Session/Round/Review/Gaps/Jobs/Profile CRUD。
- 状态机一致性检查和修复。
- PostgreSQL 与 SQLite 方言兼容。

关键约定：

- 生产使用 PostgreSQL。
- 测试使用临时 SQLite。
- JSON 字段在 PostgreSQL 用 JSONB，在 SQLite 用 TEXT。
- 任何动态 update 必须限制字段白名单。
- 切换 engine 必须 dispose 旧 engine。
- 测试候选 DB 配置必须 dispose 临时 engine。

### 3.3 `aiterate_ai.py`

负责：

- 根据设置读取 provider/base_url/api_key/model。
- 按 role 选择模型：title、answer、evaluate、review、deepen。
- 生成标题、初始回答、理解评价、追问回答、费曼题、费曼评分、复习评分。
- Tavily 搜索结果注入。
- 从 LLM 噪声输出中提取 JSON。

关键约定：

- LLM 配置只读 DB settings，不从环境变量兜底。
- `_extract_json_block()` 必须能处理嵌套对象、字符串里的 `{}`、转义和坏 JSON 后继续扫描。
- AI JSON 解析失败必须显式标记 `parse_failed`，不能静默吞错。

### 3.4 前端 Vue 模块

```text
assets/js/vue/
  main.js                  # app/router 初始化
  store.js                 # 全局状态
  api.js                   # 统一 fetch 封装
  utils.js                 # markdown/render/date/stage 工具
  components/AppRoot.js    # 全局布局、登录状态、overlay 路由
  components/SideBar.js    # 会话列表
  components/Workspace.js  # 学习/深化/复盘主界面
  components/modals/*      # 设置、新建、知识树、指挥中心
```

原则：

- 所有请求走 `api.js`。
- 401 统一派发 unauthorized 事件。
- 未认证时不加载业务数据。
- overlay 路由不能破坏背景 session tab。
- Markdown 渲染必须 XSS-safe。
- UI 两套主题共享视觉语言，只切明暗，不重做一套风格。

## 4. 数据模型

### 4.1 `sessions`

代表一个学习主题。

关键字段：

- `title`：AI 生成标题。
- `content`：用户原始输入。
- `type`：`question | viewpoint`。
- `status`：状态机当前状态。
- `material`：AI 初始学习材料。
- `score`：最终分数。
- `review_report`：费曼报告 JSON。
- `knowledge_node_id`：绑定知识树节点。
- `web_search`：是否启用联网搜索。
- `error_msg`：错误状态说明。

### 4.2 `rounds`

代表一次用户/AI 交互轮次。

- `type=take`：用户写理解，AI 评价。
- `type=press`：用户追问，AI 回答。
- `type=feynman`：费曼检验题，每题一条 round。

关键字段：

- `seq`：session 内顺序。
- `input`：用户输入或题目。
- `output`：AI 输出或用户答案。
- `eval_json`：评价 JSON。
- `score`：评分。
- `group_id`：费曼题组 ID。
- `status`：`pending | evaluated | deepening | completed` 等。

### 4.3 `learning_gaps`

薄弱点账本。

- take 评价中的 gaps 自动入库。
- 费曼/复习中的 weak_points 回流匹配已有 gap 或新建 gap。
- 支持 `open/resolved/ignored/reappeared`。

### 4.4 `review_schedule`

间隔复习计划。

- 完成学习后创建 pending 复习。
- 完成复习后自动排下一轮。
- skip 只标记 skipped，不算 completed，不排下一轮。

### 4.5 `jobs`

后台任务队列。

当前主要任务类型：`generate_session_answer`。

目标：避免 HTTP 请求长时间等待 LLM，同时支持任务恢复、失败记录和并发限制。

## 5. 状态机

```text
preparing → learning → deepening → feynman → completed
                           ↑          ↓
                           └─ revising
error 可由后台任务失败进入
```

状态含义：

- `preparing`：session 已创建，等待后台生成初始回答。
- `learning`：初始材料已生成，可以开始学习。
- `deepening`：用户已经写理解或追问。
- `feynman`：存在待提交费曼题组。
- `revising`：费曼未通过，回到修正阶段。
- `completed`：完成学习并进入复习队列。
- `error`：后台任务或 AI 调用失败。

入口 guard：

| 操作 | 允许状态 |
|---|---|
| deepen | learning, deepening, revising |
| start-feynman | deepening, revising；若已有 pending group 则幂等复用 |
| complete-feynman | feynman |
| complete | learning, deepening, revising |
| reopen | completed, revising |

## 6. 学习闭环

### 6.1 创建 session

1. 用户提交内容。
2. DB 创建 `preparing` session。
3. 创建 `generate_session_answer` job。
4. worker 调用 AI 生成标题和初始回答。
5. session 更新为 `learning`。

### 6.2 深化

- take：AI 评价用户理解，写入 round，提取 gaps，生成追问建议。
- press：AI 回答追问，写入 round，并尝试根据用户内容解决已有 gaps。

### 6.3 费曼

1. 要求至少存在一次 take。
2. 生成 2~3 道检验题。
3. 每题写一条 pending feynman round。
4. 再次 start 时复用 pending group，保证幂等。
5. complete 时逐题评分。
6. 分数达标：`completed`，保存 review_report，排复习。
7. 分数未达标：`revising`，生成 correction_plan，weak_points 回流 gaps。

### 6.4 复习

- `GET /api/review/today` 返回到期复习。
- `submit` 让用户重新解释并由 AI 评分。
- `complete` 兼容旧式直接完成。
- `skip` 标记跳过，不算掌握。

## 7. 安全设计

### 7.1 认证

- Web 登录：`POST /api/auth/login` 校验 admin token，设置 HttpOnly cookie。
- API 脚本：兼容 `X-Admin-Token`。
- `GET /api/auth/status` 返回认证状态。
- 业务接口默认需要 `_require_admin`。

### 7.2 密钥保护

- HTML 不静态注入 admin token。
- settings GET 不返回明文 API key，只返回 masked/has 标识。
- DB 配置和文档不得出现明文密码或 token。

### 7.3 前端 XSS

- Markdown 渲染优先使用 DOMPurify。
- DOMPurify 不存在时 fail-closed，只渲染 escape 后文本。
- Vue 模板中的动态 HTML 只用于受控 Markdown/SVG，外部输入必须 escape。

### 7.4 SQL 安全

- SQLAlchemy text 参数绑定。
- 动态 update 字段白名单。
- PostgreSQL 类型转换尽量用 `CAST(:x AS jsonb)`，避免 `:x::jsonb` 被 SQLAlchemy 误识别。

## 8. 性能设计

- 初始回答进入 DB job queue，不阻塞创建 session 请求。
- worker 使用并发上限，避免过多 LLM 请求同时发出。
- aiohttp ClientSession 复用，减少 TCP/TLS 开销。
- 常用列表查询限制 limit，并为 review/jobs/gaps 建索引。
- Command Center 直接聚合最关键的下一步任务，避免前端多接口拼装。

## 9. 测试设计

默认 pytest 必须满足：

- 不依赖线上服务是否启动。
- 不调用真实 LLM。
- 不污染生产 PostgreSQL。
- 不依赖历史 session 数量或固定 ID。

实现方式：

- `tests/app_fixture.py` monkeypatch DB 配置到 tmp SQLite。
- fake AI async 函数返回 deterministic 结果。
- 手动 claim job 并同步调用 `_process_generate_session_answer()`。
- 覆盖 API contract、状态机、完整 pass/fail 流程。

验证命令：

```bash
~/.hermes/venv/bin/python -m pytest -q
```

## 10. 维护边界

- 修改 DB schema：更新 `init_db()`，同时考虑 PostgreSQL/SQLite。
- 修改状态机：必须更新 guard 表和测试。
- 修改前端：必须构建 Vite，并用浏览器检查 console。
- 清理生产数据：必须先备份，保留 `profile`。
- 新文档中禁止写入任何真实 secret。
