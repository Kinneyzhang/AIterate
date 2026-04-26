# AIIterate

AIIterate 是一个个人学习迭代系统：把一个问题或观点拆成“AI 初始回答 → 用户深化理解 → 费曼检验 → 间隔复习”的闭环，并把薄弱点、复习计划、知识树进度沉淀成可追踪的学习资产。

## 核心能力

- 提问/观点输入：提交一个问题或观点，后台异步生成标题和学习材料。
- 深化学习：支持“写理解”和“追问”两类轮次；理解评价会沉淀薄弱点。
- 费曼检验：AI 生成检验题，逐题评分，达标则完成，否则回到修正阶段。
- 复习队列：完成学习后按个性化艾宾浩斯间隔排期复习。
- 指挥中心：聚合待完成费曼、今日复习、学习中、异常项。
- 知识树：学习记录可绑定知识节点，并生成掌握度与推荐下一步节点。
- 设置中心：配置 LLM provider、分角色模型、Tavily、数据库、费曼通过分。

## 技术栈

- 后端：FastAPI + SQLAlchemy Core
- 数据库：PostgreSQL（生产）/ SQLite（测试）
- 前端：Vue 3 + Vue Router + Vite 构建
- AI：OpenAI-compatible API 路由，支持按角色配置模型
- 部署：user-level systemd service `aiterate.service`

## 项目结构

```text
aiterate/
  aiterate_server.py          # FastAPI app、认证、API 路由、后台 job worker
  aiterate_db.py              # SQLAlchemy Core 数据层、迁移、状态机一致性检查
  aiterate_ai.py              # LLM 调用、Tavily 搜索、prompt 与 JSON 解析
  USER_GUIDE.md               # 用户使用文档
  index.html                  # Vite 构建入口 shell
  assets/
    app.css                   # 全局布局与组件样式
    themes/night.css          # 暗色主题
    themes/mono.css           # 亮色主题
    js/vue/                   # Vue 3 模块化前端
  config/
    db.json                   # 数据库配置（不要提交敏感信息）
    knowledge_tree.json       # 知识树
  tests/
    app_fixture.py            # 隔离测试 fixture：临时 SQLite + deterministic fake AI
    test_unit.py              # 纯逻辑单元测试
    test_api_contract.py      # 隔离 API 契约测试
    test_state_machine.py     # 隔离状态机测试
    test_full_flow_repeatable.py # 可重复全流程测试
    live_full_flow.py         # 真实服务/真实 LLM 冒烟脚本（手动运行）
```

## 本地运行

```bash
cd ~/.hermes/workspace/aiterate
~/.hermes/venv/bin/python -m uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

生产环境用 systemd：

```bash
systemctl --user restart aiterate.service
systemctl --user status aiterate.service --no-pager
journalctl --user -u aiterate.service -f
```

健康检查：

```bash
curl http://127.0.0.1:7070/healthz
```

## 前端构建

Vite 需要 Node.js `>=20.19`，当前环境建议切到 Node 24：

```bash
cd ~/.hermes/workspace/aiterate
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 24
npx vite build
systemctl --user restart aiterate.service
```

## 测试

默认测试全部使用临时 SQLite 和 fake AI，不调用真实 LLM，不污染生产数据库：

```bash
cd ~/.hermes/workspace/aiterate
~/.hermes/venv/bin/python -m pytest -q
```

重点测试：

```bash
~/.hermes/venv/bin/python -m pytest tests/test_full_flow_repeatable.py -q
~/.hermes/venv/bin/python -m pytest tests/test_api_contract.py tests/test_state_machine.py -q
```

真实服务冒烟脚本会调用线上服务和真实模型，只在需要端到端验证时手动运行：

```bash
~/.hermes/venv/bin/python tests/live_full_flow.py
```

## 数据库维护

常用健康检查：

```bash
~/.hermes/venv/bin/python - <<'PY'
import json, aiterate_db as db
print(json.dumps({
  'stats': db.get_stats(),
  'health': db.get_system_health(),
  'jobs': {'pending': db.get_pending_job_count(), 'running': db.get_running_job_count()},
  'invariants': db.check_invariants(),
}, ensure_ascii=False, default=str, indent=2))
PY
```

清理历史学习数据时，应先备份数据库；清理业务表时保留 `profile`，避免丢失设置和 admin token。

## 安全说明

- 静态源文件和构建产物只保留 `%%AITERATE_TOKEN%%` placeholder，不提交明文 admin token。
- 服务端返回首页时会把 placeholder 替换为当前 admin token，作为本机/脚本兼容；Web 登录成功后使用 HttpOnly session cookie。
- API 仍兼容 `X-Admin-Token`，用于测试和脚本。
- 设置接口只返回密钥掩码，不返回明文 API key。
- 前端 Markdown 渲染 fail-closed：DOMPurify 不存在时只输出转义文本。
- 动态 SQL update 已限制字段白名单。

## 主要 API

- `POST /api/auth/login` / `POST /api/auth/logout` / `GET /api/auth/status`
- `GET /api/ready` / `GET /api/stats` / `GET /api/command-center`
- `GET /api/sessions` / `POST /api/sessions`
- `GET /api/sessions/{id}/workspace`
- `POST /api/sessions/{id}/deepen`
- `POST /api/sessions/{id}/start-feynman`
- `POST /api/sessions/{id}/complete-feynman`
- `GET /api/review/today` / `POST /api/review/{id}/submit` / `POST /api/review/{id}/skip`
- `GET /api/maintenance/check-invariants` / `POST /api/maintenance/repair-invariants`

## 开发约定

- 修改 `assets/js/vue/`、`assets/app.css`、主题 CSS、`index.html` 后必须 `npx vite build`。
- 后端业务 SQL 需要同时考虑 PostgreSQL 和 SQLite 测试分支。
- 新增状态变更入口必须加状态机 guard，并补 isolated test。
- 不要让默认 pytest 依赖真实服务、真实 LLM 或生产历史数据。
