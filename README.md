# AIIterate

> AI-assisted iterative learning system — 把一次提问变成“学习材料 → 主动复述 → 费曼检验 → 间隔复习 → 知识资产”的闭环。

AIIterate 不是聊天工具。它更像一个个人学习操作系统：每个问题都会进入可追踪的状态机，用户必须用自己的话解释，AI 负责评价、追问、生成费曼题、识别薄弱点，并把复习计划和知识树进度沉淀下来。

## 📚 文档导航

- [用户使用文档](USER_GUIDE.md)：面向日常使用，讲清楚怎么创建学习主题、怎么写理解、怎么做费曼和复习。
- [设计文档](DESIGN.md)：面向开发维护，说明架构、状态机、数据模型、安全边界、测试策略和维护规范。
- [配置示例](config/db.json.example)：数据库配置模板。真实 `config/db.json` 已被忽略，不能提交。

README 按“入口文档”定位编写：先让读者理解项目价值，再给出可复制的启动、配置、测试、部署和维护路径；细节统一跳转到专门文档，避免 README 变成杂乱流水账。

## ✨ 核心理念

### 1. 学习必须可验证

普通 AI 问答容易停留在“看懂了”的错觉。AIIterate 强制加入主动复述与费曼检验：

```text
我问一个问题
  → AI 生成结构化学习材料
  → 我用自己的话复述理解
  → AI 评价并指出 gaps
  → 我追问或修正
  → AI 出费曼题检验
  → 通过后进入复习队列
```

### 2. 薄弱点是资产，不是临时提示

每次理解评价产生的 `gaps` 会进入 `learning_gaps` 账本。费曼失败、复习低分也会回流到同一套薄弱点模型，形成长期追踪。

### 3. 学习不是一次性完成

完成 session 后，系统按个性化艾宾浩斯间隔创建复习计划。复习不是简单打勾，而是要求重新解释，并由 AI 再次评价。

### 4. 知识树让长期学习可见

每个 session 可以绑定到知识节点。系统会聚合完成率、平均分、gap 数、待复习项，给出掌握度和下一步推荐。

## 🚀 功能总览

### 学习闭环

- 新建问题或观点，后台异步生成标题和初始学习材料。
- 支持“写理解”和“追问”两类深化轮次。
- 写理解会得到 0-100 分评价、表扬、薄弱点、结论和推荐追问。
- 至少写过一次理解后才能进入费曼检验。
- 费曼题逐题评分，通过则完成，未通过则回到修正阶段。
- 完成学习后自动创建复习计划。

### 认知资产

- `learning_gaps`：薄弱点账本，支持 open/resolved/ignored/reappeared。
- `review_report`：费曼报告，保存最终分数、强项、弱项、总结、是否通过。
- `correction_plan`：费曼失败后的修正计划。
- `knowledge_node_id`：知识树绑定关系。
- `review_schedule`：复习排期与复习反馈。

### 指挥中心

指挥中心聚合今天最该做的事：

- 待完成费曼。
- 到期复习。
- 正在学习或修正的 session。
- 未来几天的复习压力。
- 后台 job、异常 session、状态机 invariant 等系统健康信息。

### 管理与配置

- Web 登录 + HttpOnly cookie。
- `X-Admin-Token` 兼容脚本调用。
- LLM provider/base_url/model/API key 可在设置页配置。
- 支持按 role 配置模型：标题、回答、评价、复习、深化。
- Tavily API key 用于联网搜索。
- 数据库配置可在 UI 或 `config/db.json` 中管理。
- API key 读取时只返回掩码，不返回明文。

## 🧱 技术栈

- Backend：FastAPI、SQLAlchemy Core、aiohttp、Pydantic。
- Database：生产 PostgreSQL，测试临时 SQLite。
- Frontend：Vue 3、Vue Router、Vite。
- AI：OpenAI-compatible Chat Completions API，支持多 provider 与 role routing。
- Search：Tavily。
- Deploy：user-level systemd，兼容 Docker Compose。
- Test：pytest、FastAPI TestClient、deterministic fake AI。

## 📂 项目结构

```text
aiterate/
  README.md                         # 项目入口文档
  USER_GUIDE.md                     # 用户使用指南
  DESIGN.md                         # 架构与维护设计文档

  aiterate_server.py                # FastAPI app、认证、API 路由、job worker、状态机 guard
  aiterate_db.py                    # SQLAlchemy Core 数据层、schema、迁移、invariant 检查
  aiterate_ai.py                    # LLM 路由、Tavily 搜索、prompt、鲁棒 JSON 提取

  index.html                        # Vite 入口 shell
  vite.config.js                    # Vite 构建配置
  package.json                      # 前端依赖
  requirements.txt                  # Python 依赖

  assets/
    app.css                         # 全局布局与组件样式
    fonts.css                       # 字体配置
    themes/
      night.css                     # 暗色主题
      mono.css                      # 亮色主题
    js/vue/                         # 当前 Vue 3 前端源码
      main.js                       # app/router 初始化
      store.js                      # 全局状态
      api.js                        # 统一 API 封装
      components/                   # AppRoot / SideBar / TopBar / Workspace / Modals
    vendor/                         # 本地 vendor 静态依赖

  public/                           # Vite public assets
  config/
    db.json.example                 # 数据库配置模板
    knowledge_tree.json             # 知识树定义

  tests/
    app_fixture.py                  # 隔离测试 fixture：tmp SQLite + fake AI
    test_unit.py                    # 纯逻辑单测
    test_api_contract.py            # API 契约测试，默认隔离不打真实 LLM
    test_state_machine.py           # 状态机与 invariant 测试
    test_full_flow_repeatable.py    # 可重复全流程测试
    live_full_flow.py               # 真实服务/真实 LLM 冒烟脚本，手动运行

  Dockerfile
  docker-compose.yml
```

## ⚡ 快速开始

### 1. 准备 Python 环境

项目依赖写在 `requirements.txt`。在当前机器建议使用 Hermes venv：

```bash
cd ~/vibe/aiterate
~/.hermes/venv/bin/python -m pip install -r requirements.txt
```

如果在新机器部署，推荐 Python 3.11+。

### 2. 准备数据库配置

复制模板：

```bash
cd ~/vibe/aiterate
cp config/db.json.example config/db.json
```

生产建议 PostgreSQL：

```json
{
  "type": "postgresql",
  "host": "127.0.0.1",
  "port": 5432,
  "dbname": "aiterate",
  "user": "aiterate",
  "password": "CHANGE_ME"
}
```

测试和轻量体验可用 SQLite：

```json
{
  "type": "sqlite",
  "sqlite_path": "~/.aiterate/data.db"
}
```

注意：真实 `config/db.json` 不应提交；文档、提交和日志里都不能出现真实数据库密码、admin token 或 LLM API key。

### 3. 启动后端

```bash
cd ~/vibe/aiterate
~/.hermes/venv/bin/python -m uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

访问：

```text
http://127.0.0.1:7070
```

健康检查：

```bash
curl http://127.0.0.1:7070/healthz
```

### 4. 配置 AI

首次登录后进入“设置”：

```json
{
  "llm": {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-...",
    "model": "deepseek-chat",
    "roles": {
      "title": {"model": "deepseek-chat"},
      "answer": {"model": "deepseek-chat"},
      "evaluate": {"model": "deepseek-chat"},
      "review": {"model": "deepseek-chat"},
      "deepen": {"model": "deepseek-chat"}
    }
  },
  "tavily_api_key": "tvly-...",
  "feynman_pass_score": 60
}
```

role 含义：

- `title`：生成 session 标题。
- `answer`：生成初始学习材料。
- `evaluate`：评价用户写下的理解。
- `review`：生成费曼题、评价费曼答案、评价复习解释。
- `deepen`：回答追问、生成深化建议。

## 🖥️ 生产运行

当前部署使用 user-level systemd：

```bash
systemctl --user restart aiterate.service
systemctl --user status aiterate.service --no-pager
journalctl --user -u aiterate.service -f
```

服务地址：

```text
http://192.168.31.222:7070
```

配置就绪检查需要认证。脚本调用可以带 `X-Admin-Token`：

```bash
curl -H "X-Admin-Token: $AITERATE_ADMIN_TOKEN" http://127.0.0.1:7070/api/ready
```

## 🐳 Docker Compose

项目包含基础 Dockerfile 与 compose 文件：

```bash
docker compose up -d --build
```

默认挂载：

- `./data:/data`：SQLite 数据目录。
- `./config:/app/config`：数据库配置。

如使用 PostgreSQL，可按 `docker-compose.yml` 中注释启用 postgres 服务，并修改 `config/db.json`。

## 🧪 测试

默认 pytest 必须满足三条原则：

- 不依赖线上服务是否启动。
- 不调用真实 LLM。
- 不污染生产 PostgreSQL。

运行全量离线测试：

```bash
cd ~/vibe/aiterate
~/.hermes/venv/bin/python -m pytest -q
```

重点回归：

```bash
~/.hermes/venv/bin/python -m pytest tests/test_full_flow_repeatable.py -q
~/.hermes/venv/bin/python -m pytest tests/test_api_contract.py tests/test_state_machine.py -q
```

真实服务冒烟脚本会调用真实服务和真实模型，会创建真实 session，只在明确需要端到端验证时手动运行：

```bash
~/.hermes/venv/bin/python tests/live_full_flow.py
```

## 🎨 前端开发

Vite 8 需要 Node.js `>=20.19`。当前环境建议使用 Node 24：

```bash
cd ~/vibe/aiterate
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 24
npx vite build
systemctl --user restart aiterate.service
```

本地开发代理：

```bash
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 24
npx vite --host 0.0.0.0
```

开发约定：

- 修改 `assets/js/vue/`、`assets/app.css`、`assets/themes/`、`index.html` 或 `vite.config.js` 后必须重新构建。
- 所有业务请求必须走 `assets/js/vue/api.js`。
- 未认证时不要加载业务数据。
- Markdown 渲染必须 XSS-safe。
- UI 修改要保持暗亮主题一致，不要只改一套主题。

## 🔌 API 概览

除 `/`、`/favicon.svg`、`/healthz`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/status` 外，业务 API 默认需要管理员认证。

### Auth

- `POST /api/auth/login`：提交 `{ "token": "..." }`，成功后设置 HttpOnly cookie。
- `POST /api/auth/logout`：清除当前 cookie session。
- `GET /api/auth/status`：检查当前请求是否已认证。

### Session

- `GET /api/sessions?limit=200`：会话列表。
- `POST /api/sessions`：创建 session，body 包含 `content`、`type`、`web_search`、`knowledge_node_id`。
- `GET /api/sessions/{id}/workspace`：聚合 workspace 数据。
- `POST /api/sessions/{id}/deepen`：写理解或追问。
- `POST /api/sessions/{id}/start-feynman`：生成或复用费曼题组。
- `POST /api/sessions/{id}/complete-feynman`：提交费曼答案。
- `POST /api/sessions/{id}/complete`：手动完成学习。
- `POST /api/sessions/{id}/reopen`：重新打开已完成或修正中的 session。

### Knowledge & Review

- `GET /api/knowledge-tree`：知识树。
- `GET /api/knowledge-tree/mastery`：知识树掌握度。
- `GET /api/knowledge-tree/recommend`：推荐下一步节点。
- `PATCH /api/sessions/{id}/knowledge-node`：绑定或解绑 session 的知识节点。
- `GET /api/review/today`：到期复习。
- `POST /api/review/{id}/submit`：提交复习解释并由 AI 评价。
- `POST /api/review/{id}/skip`：跳过本次复习，不算完成。

### Maintenance

- `GET /api/jobs/status`：后台任务状态。
- `GET /api/command-center`：指挥中心聚合数据。
- `GET /api/maintenance/check-invariants`：状态机一致性检查。
- `POST /api/maintenance/repair-invariants?dry_run=true|false`：自动修复可修复的不一致。
- `GET /api/report/weekly`：生成学习周报 Markdown。

## 🧭 状态机速览

```text
preparing → learning → deepening → feynman → completed
                            ↑          ↓
                            └─ revising
error 可由后台 job 或 AI 调用失败进入
```

入口约束：

- `deepen` 只允许 `learning/deepening/revising`。
- `start-feynman` 只允许 `deepening/revising`，且至少有一次 `take`。
- `complete-feynman` 只允许 `feynman`。
- `complete` 只允许 `learning/deepening/revising`。
- `reopen` 只允许 `completed/revising`。

非法状态会返回 `409 Conflict`，避免把学习记录推进到不可解释的状态。

## 🛠️ 运维诊断

常用健康检查：

```bash
cd ~/vibe/aiterate
~/.hermes/venv/bin/python - <<'PY'
import json
import aiterate_db as db
print(json.dumps({
  "stats": db.get_stats(),
  "health": db.get_system_health(),
  "jobs": {
    "pending": db.get_pending_job_count(),
    "running": db.get_running_job_count(),
  },
  "invariants": db.check_invariants(),
}, ensure_ascii=False, default=str, indent=2))
PY
```

常见问题优先级：

1. `/healthz` 是否正常。
2. `jobs` 是否有 stuck running/pending。
3. `check_invariants()` 是否有 error 级别问题。
4. 浏览器 console 是否有认证竞态、JS exception 或构建产物未更新。
5. LLM settings 是否缺 provider/base_url/api_key/model。

## 🔐 安全边界

- 不提交真实 `config/db.json`。
- 不在文档、日志、测试快照中写真实 token、数据库密码或 LLM key。
- 设置接口只返回 `api_key_masked` 和 `has_api_key`。
- Web 端使用 HttpOnly cookie；脚本兼容 `X-Admin-Token`。
- 前端 Markdown 使用 DOMPurify；DOMPurify 不可用时 fail-closed。
- 动态 SQL update 必须走字段白名单。

## 🤝 开发规范

- 新增 API：同步更新 README API 概览、DESIGN 设计说明和测试。
- 修改状态机：同步更新状态机图、入口 guard、invariant 检查和状态机测试。
- 修改 DB schema：更新 `init_db()`，同时考虑 PostgreSQL 和 SQLite 测试分支。
- 修改前端：重新构建 Vite，必要时用浏览器验证 console。
- 修改 AI JSON 输出：必须保留 `parse_failed` 标记，不允许静默 fallback。
- 新增文档：避免写真实 secret，命令要可复制，说明副作用。

## 📌 当前定位

AIIterate 是个人学习系统，不是面向公网的多租户 SaaS。默认假设部署在可信内网或个人服务器上。若要公开暴露，需要额外补充：反向代理 TLS、强密码策略、速率限制、审计日志、备份恢复流程和更严格的权限模型。
