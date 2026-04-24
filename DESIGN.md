# AIIterate 系统设计文档

> 版本：v3.1 | 最后更新：2026-04

---

## 目录

1. [项目简介](#1-项目简介)
2. [整体架构](#2-整体架构)
3. [目录结构](#3-目录结构)
4. [数据模型](#4-数据模型)
5. [后端模块](#5-后端模块)
6. [前端模块](#6-前端模块)
7. [API 接口](#7-api-接口)
8. [学习流程](#8-学习流程)
9. [LLM 配置体系](#9-llm-配置体系)
10. [主题系统](#10-主题系统)
11. [部署说明](#11-部署说明)

---

## 1. 项目简介

AIIterate（AI 迭代学习系统）是一个以**问题为驱动、AI 全程伴学**的个人学习操作系统，核心循环：提出问题 → AI 生成学习材料 → 写下理解 → AI 评分深化 → 追问拓展 → 费曼自测验证掌握程度。

核心设计理念：
- **问题驱动**：每次学习以一个问题为起点
- **AI 伴学**：全程 LLM 辅助，回答、评价、深化、费曼出题
- **状态机驱动**：每个学习会话严格遵循 `draft → active → completed` 状态流转
- **多维迭代**：支持深化追问（Deepen）和费曼自测（Feynman）两种强化路径
- **自托管**：完全本地部署，数据存入 PostgreSQL，无需外部服务

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────┐
│                     Browser (SPA)                   │
│  index.html  ←→  assets/js/*.js  ←→  assets/*.css  │
└────────────────────────┬────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────┐
│            FastAPI  (aiterate_server.py)             │
│  路由层 / 参数校验 / 后台任务调度                        │
└───────┬─────────────────┬───────────────────────────┘
        │                 │
┌───────▼───────┐  ┌──────▼──────────────┐
│aiterate_db.py │  │  aiterate_ai.py      │
│  PostgreSQL   │  │  LLM + Tavily调用    │
│  CRUD 封装    │  │  Prompt 构建 / 路由   │
└───────┬───────┘  └──────┬──────────────┘
        │                 │
┌───────▼─────────────────▼───────────────────────────┐
│                  PostgreSQL (aiterate DB)            │
│         sessions  /  rounds  /  profile             │
└─────────────────────────────────────────────────────┘
```

**技术栈：**

| 层次 | 技术 |
|------|------|
| 前端 | 原生 HTML/CSS/JS（无框架，SPA 架构） |
| 后端 | Python 3.11 + FastAPI + uvicorn |
| 数据库 | PostgreSQL（psycopg2 直连） |
| AI 调用 | aiohttp 异步 HTTP → OpenAI-compatible API |
| 主题 | 双 CSS 文件（night.css / mono.css）+ JS 切换 |
| 字体 | LXGW WenKai Screen（霞鹜文楷屏幕版，subset 分片加载） |

---

## 3. 目录结构

```
aiterate/
├── index.html              # 单页应用入口
├── aiterate_server.py      # FastAPI 路由层
├── aiterate_db.py          # 数据库 CRUD 封装（PostgreSQL）
├── aiterate_ai.py          # LLM 调用 / Prompt 构建
├── aiterate_flow.py        # 业务流程编排（已合并入 server）
├── assets/
│   ├── app.css             # 全局基础样式（含移动端适配）
│   ├── fonts.css           # 字体声明（subset 分片）
│   ├── fonts/              # LXGW WenKai + FandolFang 字体文件
│   ├── themes/
│   │   ├── night.css       # 暗色主题（全部规则带 scope 前缀）
│   │   └── mono.css        # 亮色主题（默认）
│   └── js/
│       ├── api.js          # fetch 封装，统一错误处理
│       ├── app.js          # 主入口：初始化 / 主题切换 / 全局状态
│       ├── modal.js        # 新建/编辑会话 Modal
│       ├── settings.js     # 设置面板（provider / model / Tavily）
│       ├── sidebar.js      # 左侧会话列表 / 统计
│       ├── utils.js        # 公共工具函数
│       └── workspace.js    # 右侧工作区（轮次渲染 / 交互逻辑）
├── config/
│   └── knowledge_tree.json # 知识树配置（领域 / 话题树形结构）
└── tests/
    ├── test_knowledge_tree.py
    ├── test_aiterate_flow.py
    └── test_learning_sessions_api.py
```

---

## 4. 数据模型

### 4.1 sessions（学习会话）

```sql
CREATE TABLE sessions (
    id          SERIAL PRIMARY KEY,
    title       TEXT        NOT NULL,       -- AI 生成的标题
    content     TEXT,                       -- 原始问题/材料
    type        TEXT        NOT NULL DEFAULT 'question',  -- 会话入口类型
    status      TEXT        NOT NULL DEFAULT 'draft',     -- 状态机
    material    TEXT,                       -- AI 生成的学习材料（正式回答）
    score       SMALLINT,                   -- 费曼完成后的综合得分（0-100）
    error_msg   TEXT,                       -- 异步任务失败时的错误信息
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**status 状态机：**

```
draft ──(AI处理完)──► active ──(用户完成)──► completed
  │                                              │
  └──(处理失败)──► error          ◄──(重新开始)──┘
```

| status | 含义 |
|--------|------|
| `draft` | 刚创建，AI 正在后台生成 material |
| `active` | material 已就绪，用户可开始迭代 |
| `completed` | 用户主动完成，带有综合 score |
| `error` | AI 处理失败，error_msg 记录原因 |

**type 枚举：**

| type | 含义 |
|------|------|
| `question` | 以一个问题为起点 |
| `article` | 以一篇文章/材料为起点 |

---

### 4.2 rounds（学习轮次）

```sql
CREATE TABLE rounds (
    id            SERIAL PRIMARY KEY,
    session_id    INTEGER     NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq           SMALLINT    NOT NULL,    -- 该会话内的顺序编号（从1开始）
    type          TEXT        NOT NULL,    -- take | press | feynman
    input         TEXT,                   -- take/press: 用户文本; feynman: 单道题目文字
    output        TEXT,                   -- take/press: AI回复;  feynman: 用户作答文字
    score_comment TEXT,                   -- feynman: 单题 AI 评价文字
    score         SMALLINT,               -- take/feynman 有分; press 无
    group_id      INTEGER,                -- feynman 专用：同一轮出题的组标识（= 该组第一题 id）
    status        TEXT        NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, seq)
);
```

**type 枚举：**

| type | input | output | score_comment | score | group_id |
|------|-------|--------|---------------|-------|----------|
| `take` | 用户的"理解"文本 | AI 评价 + 建议 | — | ✓ | — |
| `press` | 用户的"追问"文本 | AI 的追问回答 | — | ✗ | — |
| `feynman` | 单道题目文字 | 用户对该题的作答 | AI 对该题的评价 | ✓ (0-100) | ✓ |

**feynman 一组多题示例（3 条独立 round）：**

```
seq=3  type=feynman  group_id=101  input="请解释 TCP 三次握手"   output="..."  score=82
seq=4  type=feynman  group_id=101  input="为什么不能两次握手？"   output="..."  score=75
seq=5  type=feynman  group_id=101  input="SYN Flood 原理是什么"  output="..."  score=90
```

同一组题共享 `group_id`（= 第一条 round 的 id），前端按 group_id 聚合展示，计算组内平均分。

---

### 4.3 profile（用户配置）

```sql
CREATE TABLE profile (
    id         TEXT        PRIMARY KEY DEFAULT 'default',
    theme      TEXT        NOT NULL DEFAULT 'night',   -- night | mono
    settings   JSONB       NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**settings JSONB 结构：**

```json
{
  "llm": {
    "provider": "deepseek",
    "base_url":  "https://api.deepseek.com/v1",
    "api_key":   "sk-...",
    "model":     "deepseek-v4-pro",
    "roles": {
      "title":    { "provider": "", "base_url": "", "api_key": "", "model": "" },
      "answer":   { ... },
      "evaluate": { ... },
      "review":   { ... },
      "deepen":   { ... }
    }
  },
  "tavily_api_key": "tvly-..."
}
```

- **roles 覆盖**：每个 LLM 角色可独立指定 provider/model，留空则 fallback 到全局配置
- **5 个 LLM 角色**：`title`（标题生成）、`answer`（材料生成）、`evaluate`（理解评价）、`review`（追问回答）、`deepen`（深化分析）

---

### 4.4 knowledge_tree.json（知识树）

文件型配置，不入库。结构：

```json
[
  {
    "domain": "cs",
    "label": "计算机",
    "topics": [
      { "id": "cs-network", "label": "网络" },
      { "id": "cs-os",      "label": "操作系统" }
    ]
  }
]
```

支持领域：`cs`（计算机）、`write`（写作）、`psych`（心理学）、`phil`（哲学）

---

## 5. 后端模块

### 5.1 aiterate_server.py

FastAPI 应用主文件，负责：
- 路由注册与参数校验（Pydantic Models）
- 后台任务调度（`BackgroundTasks`）：AI 处理在后台异步执行，不阻塞 HTTP 响应
- 静态文件托管（`/assets`）
- 异常处理（`RuntimeError` → JSON 格式错误响应）

**后台任务模式：**

```python
# 创建会话时，AI 处理异步进行
@app.post("/api/sessions")
async def create_session(body: ..., bg: BackgroundTasks):
    session_id = db.create_session(...)
    bg.add_task(_process_session, session_id)  # 立即返回，后台跑 AI
    return {"id": session_id, "status": "draft"}
```

前端通过轮询 `GET /api/sessions/{id}` 检测 `status` 从 `draft` 变为 `active`。

---

### 5.2 aiterate_db.py

PostgreSQL CRUD 封装层，设计原则：
- 每个函数独立开关连接（无连接池，适合单用户本地部署）
- `RealDictCursor` 使行数据自动序列化为 dict
- `next_seq()` 用 `MAX(seq)+1` 而非 `len(rounds)+1`，避免历史记录重复序号
- feynman 每题独立一条 round，通过 `group_id` 聚合同一轮出题
- `upsert_profile()` 支持 `settings__llm` 前缀语法做深层合并

---

### 5.3 aiterate_ai.py

LLM 调用引擎，负责：

**Prompt 构建**：针对不同角色（answer/evaluate/review/deepen/title）构建专项 System Prompt，注入领域上下文（`DOMAIN_CONTEXT`）。

**多 Provider 路由**：

```python
def _get_role_cfg(settings, role) -> dict:
    """role 级配置 → 全局配置 fallback"""
    llm = settings.get("llm", {})
    role_cfg = llm.get("roles", {}).get(role, {})
    return {
        "base_url": role_cfg.get("base_url") or llm.get("base_url", ""),
        "api_key":  role_cfg.get("api_key")  or llm.get("api_key",  ""),
        "model":    role_cfg.get("model")    or llm.get("model",    ""),
    }
```

**Tavily 联网搜索**：时效性问题自动触发（关键词检测），搜索结果注入 Prompt context。

**JSON 鲁棒解析**：`_extract_json_block()` 从 LLM 原始输出中提取 `{}` 或 `[]` 块，兼容 LLM 在 JSON 外输出多余文本的情况。

---

## 6. 前端模块

### 6.1 整体布局

```
┌──────────────────────────────────────────────┐
│  header（标题 + 主题切换 + 设置按钮）              │
├────────────────┬─────────────────────────────┤
│  sidebar       │  workspace                  │
│  ┌──────────┐  │  ┌──────────────────────┐   │
│  │ 统计卡片  │  │  │   会话标题 + 状态     │   │
│  ├──────────┤  │  ├──────────────────────┤   │
│  │ 会话列表  │  │  │   material（学习材料）│   │
│  │（可搜索） │  │  ├──────────────────────┤   │
│  └──────────┘  │  │   轮次列表（rounds）  │   │
│                │  ├──────────────────────┤   │
│                │  │   输入区（take/press）│   │
└────────────────┴──┴──────────────────────────┘
```

### 6.2 api.js

统一 fetch 封装，核心设计：

```javascript
async function request(method, path, body) {
    const resp = await fetch(path, { method, body: JSON.stringify(body) });
    const raw = await resp.text();          // 先读 text，避免 body stream 二次读取
    const data = JSON.parse(raw);
    if (!resp.ok) throw new Error(data.detail || raw);
    return data;
}
```

### 6.3 app.js

全局入口，负责：
- 初始化（加载 profile、settings、knowledge tree）
- 主题切换（`toggleTheme`）：切换两个 `<link>` 标签的 `disabled` 属性，同步写 API
- 全局事件监听（键盘快捷键、ESC 关闭 Modal）
- 会话轮询（`draft` 状态下每 2s 轮询一次，直到 `active`）

### 6.4 workspace.js

工作区核心逻辑，负责：
- `renderSession()`：渲染 material + 所有历史 rounds
- `buildTakeRoundCard()` / `buildPressRoundCard()` / `buildDeepenRoundCard()`：不同类型轮次的卡片渲染
- `submitTake()`：提交理解（`POST /api/sessions/{id}/deepen`，action=`take`）
- `submitPress()`：提交追问（action=`press`）
- `startFeynman()` / `completeFeynman()`：费曼自测流程
- 输入区切换：理解模式（右）/ 追问模式（左）

### 6.5 settings.js

设置面板，支持：
- Provider 快速切换（DeepSeek / Kimi / 豆包 / Copilot / 自定义）
- Provider 切换时自动填充 `base_url`，显示模型建议提示
- 每个 LLM 角色独立配置（可展开的 role 覆盖区域）
- 自定义 select 控件（`csel`）：替代原生 select，避免 `backdrop-filter` 与原生 popup 合成层冲突
- Tavily API Key 配置

---

## 7. API 接口

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/healthz` | 健康检查 |
| GET | `/api/ready` | LLM / Tavily 就绪状态 |
| GET | `/api/stats` | 统计数据（总会话数、完成数、平均分、近7日） |
| GET | `/api/knowledge-tree` | 知识树配置 |

### Profile & Settings

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profile` | 获取用户配置（theme + settings） |
| PATCH | `/api/profile` | 更新 theme |
| GET | `/api/settings` | 获取 settings |
| PATCH | `/api/settings` | 更新 settings（支持 `llm` / `tavily_api_key`） |

### Sessions

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 获取会话列表（最近20条） |
| POST | `/api/sessions` | 创建新会话，后台触发 AI 处理 |
| GET | `/api/sessions/{id}` | 获取单个会话详情 |
| GET | `/api/sessions/{id}/rounds` | 获取会话所有轮次 |
| GET | `/api/sessions/{id}/workspace` | 获取工作区数据（session + rounds 合并） |
| POST | `/api/sessions/{id}/deepen` | 提交轮次（`action`: take/press） |
| POST | `/api/sessions/{id}/start-feynman` | 启动费曼自测（AI 出题） |
| POST | `/api/sessions/{id}/complete-feynman` | 提交费曼答案，AI 评分 |
| POST | `/api/sessions/{id}/complete` | 完成会话 |
| POST | `/api/sessions/{id}/reopen` | 重新开放已完成的会话 |

### POST /api/sessions 请求体

```json
{
  "title": "TCP 三次握手的原理",
  "content": "为什么 TCP 建立连接需要三次握手？",
  "type": "question",
  "domain": "cs"
}
```

### POST /api/sessions/{id}/deepen 请求体

```json
{
  "action": "take",
  "text": "三次握手是为了确保双方的发送和接收能力都正常..."
}
```

```json
{
  "action": "press",
  "text": "为什么不能是四次握手？"
}
```

---

## 8. 学习流程

### 8.1 标准流程

```
1. 用户输入问题/材料
         │
         ▼
2. 创建 session（status=draft）
   后台 AI 生成 material（正式学习回答）
         │
         ▼
3. session.status = active
   前端展示 material，用户阅读学习
         │
         ▼
4. 用户写"理解"→ 提交 take
   AI 评价理解，给出得分 + 深化建议
   写入 rounds（type=take）
         │
    ┌────┴──────┐
    │           │
    ▼           ▼
5a. 追问        5b. 费曼自测
  press轮次       start-feynman
  AI直接回答      AI出N道题
                  用户作答
                  complete-feynman
                  AI评分
         │
         ▼
6. 用户点"完成"→ session.status = completed
```

### 8.2 状态与轮次对应关系

```
session.status=active
  rounds: [
    { seq:1, type:'take',    input:'我的理解...', output:'AI评价...',  score:82 },
    { seq:2, type:'press',   input:'为什么?...',  output:'AI解释...',  score:null },
    { seq:3, type:'feynman', group_id:3, input:'题1', output:'答1',   score:75 },
    { seq:4, type:'feynman', group_id:3, input:'题2', output:'答2',   score:90 },
    ...
  ]
```

---

## 9. LLM 配置体系

### Provider 预设

| Provider | base_url |
|----------|----------|
| deepseek | `https://api.deepseek.com/v1` |
| kimi     | `https://api.moonshot.cn/v1` |
| doubao   | `https://ark.cn-beijing.volces.com/api/v3` |
| copilot  | `https://api.githubcopilot.com` |
| 自定义   | 用户填写 |

### 模型建议

| Provider | 推荐模型 |
|----------|---------|
| DeepSeek | `deepseek-v4-pro` / `deepseek-v4-flash` / `deepseek-chat` |
| Kimi     | `moonshot-v1-8k` / `moonshot-v1-32k` |
| 豆包     | `ep-xxxx`（需先在控制台创建推理接入点） |
| Copilot  | `gpt-4o` / `claude-sonnet-4` |

### Role 优先级

```
role-specific config（非空时） > 全局 llm config > 报错
```

---

## 10. 主题系统

两套 CSS 主题通过 `<link>` 标签的 `disabled` 属性切换：

```html
<link id="themeStylesheet"    href="/assets/themes/night.css">
<link id="themeStylesheetAlt" href="/assets/themes/mono.css" disabled>
```

**关键设计决策**：

- **night.css 所有规则带 scope 前缀**（`.night-theme .xxx`），避免主题切换时触发全局 reflow，消除抖动
- **csel 替代原生 select**：`backdrop-filter: blur(4px)` 的 Modal 与原生 select popup 存在 GPU 合成层冲突，用自定义下拉控件解决
- 主题状态持久化在 `profile.theme` 字段，刷新后自动恢复

---

## 11. 部署说明

### 依赖

```
Python 3.11+
PostgreSQL 14+

pip install fastapi uvicorn psycopg2-binary aiohttp python-multipart
```

### 环境变量（可选，有默认值）

```bash
AITERATE_PG_HOST=127.0.0.1
AITERATE_PG_PORT=5432
AITERATE_PG_DBNAME=aiterate
AITERATE_PG_USER=geekinney
AITERATE_PG_PASSWORD=your_password
```

### 初始化数据库

```bash
cd aiterate
python aiterate_db.py   # 自动建表 + 迁移
```

### 启动服务

```bash
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

### systemd 服务

参见 `devops/systemd-wrapper` skill，服务名 `aiterate.service`。

### 数据备份

```bash
pg_dump -U geekinney aiterate > aiterate_backup.sql
```

---

*设计文档由 Hermes Agent 根据源码自动生成并维护。*
