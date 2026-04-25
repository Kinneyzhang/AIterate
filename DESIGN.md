# AIIterate 系统设计文档

> 版本：v0.0.3 | 最后更新：2026-04-25

---

## 目录

1. [项目简介](#1-项目简介)
2. [整体架构](#2-整体架构)
3. [目录结构](#3-目录结构)

---

## 1. 项目简介

AIIterate v0.0.3 前端全面迁移至 **Vue 3 + Vue Router**（ES Module，importmap 加载，零构建），后端 API 不变。

**v0.0.3 核心变化：**
- 前端框架：原生 JS → Vue 3 Composition API + Vue Router
- 组件化：12 个 Vue SFC 风格组件（defineComponent + template string）
- 响应式状态：`reactive()` 全局 store 替代手动 DOM 操作
- CDN 加载：unpkg importmap，零构建步骤，保持极简部署
12. [部署说明](#12-部署说明)

---

## 1. 项目简介

AIIterate（AI 迭代学习系统）是一个以**问题为驱动、AI 全程伴学**的个人学习操作系统，核心循环：提出问题 → AI 生成学习材料 → 写下理解 → AI 评分 + 定位薄弱点 → 追问深化 → 费曼自测验证掌握程度 → 生成学习报告 → 自动排期复习。

**v0.0.2 核心变化：**
- 安全加固：Admin token 鉴权、密钥掩码、DOMPurify XSS 防护、CORS 白名单
- 数据一致性：round 追加/Feynman 创建&提交全事务化、DB 配置先测后存
- 知识地图：卡片式布局，去掉进度追踪，改为标记已触碰知识点
- 指挥中心：待完成费曼、今日复习、待修正 session 一览
- 薄弱点追踪 + 学习报告 + 间隔复习
- SVG 图标系统：17 个内联 SVG 替代 emoji，全平台一致渲染
- 移动端适配：模态框全屏、汉堡菜单对齐
- 测试体系：19 个离线单测 + live AI 回归测试分离

核心设计理念：
- **问题驱动**：每次学习以一个问题为起点
- **AI 伴学**：全程 LLM 辅助，回答、评价、深化、费曼出题
- **状态机驱动**：每个学习会话严格遵循 `preparing → learning → deepening → feynman → completed` 状态流转
- **多维迭代**：支持深化追问（Deepen）和费曼自测（Feynman）两种强化路径
- **认知沉淀**：薄弱点持久化、费曼报告、间隔复习——每次学习都留下可复用资产
- **自托管**：完全本地部署，数据本地，无需外部服务

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────┐
│                     Browser (SPA)                   │
│  index.html  ←→  assets/js/*.js  ←→  assets/*.css  │
│  DOMPurify XSS 防护 / Admin Token 注入               │
└────────────────────────┬────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────┐
│            FastAPI  (aiterate_server.py)             │
│  路由层 / 参数校验 / 鉴权 / 后台任务调度                │
└───────┬─────────────────┬───────────────────────────┘
        │                 │
┌───────▼───────┐  ┌──────▼──────────────┐
│aiterate_db.py │  │  aiterate_ai.py      │
│  SQLAlchemy   │  │  LLM + Tavily调用    │
│  Core 多库    │  │  Prompt 构建 / 路由   │
│  事务化 CRUD   │  │  JSON 鲁棒解析       │
└───────┬───────┘  └──────┬──────────────┘
        │                 │
┌───────▼─────────────────▼───────────────────────────┐
│          Database（SQLite / PG / MySQL）            │
│   sessions / rounds / review_reports / profile      │
└─────────────────────────────────────────────────────┘
```

**技术栈：**

| 层次 | 技术 |
|------|------|
| 前端 | 原生 HTML/CSS/JS（ES Module，无框架 SPA） |
| 后端 | Python 3.11 + FastAPI + uvicorn |
| 数据库 | SQLAlchemy Core（SQLite / PostgreSQL / MySQL） |
| AI 调用 | aiohttp 异步 HTTP → OpenAI-compatible API |
| 安全 | DOMPurify + Admin Token + 密钥掩码 + CORS 白名单 |
| 图标 | 内联 SVG（17 个 Lucide 风格图标） |
| 主题 | 双 CSS 文件（night.css / mono.css）+ `data-theme` 切换 |
| 字体 | LXGW WenKai Screen（霞鹜文楷屏幕版，subset 分片加载） |

---

## 3. 目录结构

```
aiterate/
├── index.html              # SPA 入口，Admin Token 注入
├── aiterate_server.py      # FastAPI 路由层（含鉴权中间件）
├── aiterate_db.py          # 数据库 CRUD（SQLAlchemy Core，事务上下文）
├── aiterate_ai.py          # LLM 调用 / Prompt 构建 / Tavily
├── assets/
│   ├── app.css             # 全局基础样式（含移动端全屏适配）
│   ├── fonts.css           # 字体声明（subset 分片）
│   ├── fonts/              # LXGW WenKai + FandolFang 字体文件
│   ├── themes/
│   │   ├── night.css       # 暗色主题（全部规则带 scope 前缀）
│   │   └── mono.css        # 亮色主题
│   └── js/
│       ├── api.js          # fetch 封装，统一错误处理
│       ├── app.js          # 主入口：初始化/轮询/知识地图/指挥中心
│       ├── modal.js        # 新建 session Modal + 知识节点推荐
│       ├── settings.js     # 设置面板（5 tab + 密钥掩码 + 角色配置）
│       ├── sidebar.js      # 左侧会话列表
│       ├── utils.js        # 工具函数 + SVG 图标库（17 个图标）
│       └── workspace.js    # 工作区（学习/深化/费曼三 tab + 薄弱点+报告）
├── config/
│   └── knowledge_tree.json # 知识树配置（4 领域树形结构）
└── tests/
    ├── conftest.py         # pytest 配置（mock DB/fixtures）
    ├── test_unit.py        # 19 个离线单测（CI 稳定）
    └── live_full_flow.py   # 全量 AI 回归测试（手动运行）
```

---

## 4. 数据模型

### 4.1 sessions（学习会话）

```sql
CREATE TABLE sessions (
    id          SERIAL PRIMARY KEY,
    title       TEXT        NOT NULL,
    content     TEXT,
    type        TEXT        NOT NULL DEFAULT 'question',
    status      TEXT        NOT NULL DEFAULT 'preparing',
    material    TEXT,
    score       SMALLINT,
    knowledge_node_id TEXT,
    error_msg   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**status 状态机：**

```
preparing ──(AI生成完)──► learning ──(提交理解)──► deepening
    │                        │                         │
    └──(处理失败)──► error   │               (费曼通过)─┘
                             │                    │
                     (发起费曼)──► feynman ──(费曼未通过)──► revising
                                      │
                               (费曼通过)──► completed
```

| status | 含义 |
|--------|------|
| `preparing` | 刚创建，AI 正在后台生成学习材料 |
| `learning`  | 材料就绪，用户可开始学习/迭代 |
| `deepening` | 用户提交了理解，正在深化追问阶段 |
| `revising`  | 费曼未通过，退回重新巩固 |
| `feynman`   | 费曼检验进行中（AI 已出题，用户答题中） |
| `completed` | 费曼通过，学习完成 |
| `error`     | AI 处理失败 |

**type 枚举：**

| type | 含义 |
|------|------|
| `question`  | 以一个问题为起点 |
| `viewpoint` | 以一个观点/论点为起点 |

---

### 4.2 rounds（学习轮次）

```sql
CREATE TABLE rounds (
    id            SERIAL PRIMARY KEY,
    session_id    INTEGER     NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq           SMALLINT    NOT NULL,
    type          TEXT        NOT NULL,    -- take | press | feynman
    input         TEXT,
    output        TEXT,
    score_comment TEXT,
    score         SMALLINT,
    group_id      INTEGER,
    status        TEXT        NOT NULL DEFAULT 'pending',
    eval_json     JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, seq)
);
```

**type 枚举：**

| type | input | output | score | group_id | eval_json |
|------|-------|--------|-------|----------|-----------|
| `take` | 用户的理解文本 | AI 评价 + 建议 | ✓ | — | gaps/verdict |
| `press` | 用户的追问文本 | AI 的追问回答 | ✗ | — | — |
| `feynman` | 单道题目文字 | 用户作答 | ✓ (0-100) | ✓ | — |

**feynman 一组多题示例（3 条独立 round）：**

```
seq=3  type=feynman  group_id=101  input="请解释 TCP 三次握手"   output="..."  score=82
seq=4  type=feynman  group_id=101  input="为什么不能两次握手？"   output="..."  score=75
seq=5  type=feynman  group_id=101  input="SYN Flood 原理是什么"  output="..."  score=90
```

**事务化保证：** `create_feynman_group()` 和 `complete_feynman_group()` 在单个事务内完成所有题的写入/评分/状态流转，防止中途失败留下脏数据。`create_round_with_seq()` 用 `SELECT ... FOR UPDATE` 锁 session 行，防止并发 seq 冲突。

---

### 4.3 profile（用户配置）

```sql
CREATE TABLE profile (
    id         TEXT        PRIMARY KEY DEFAULT 'default',
    theme      TEXT        NOT NULL DEFAULT 'night',
    settings   JSONB       NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**settings JSONB 结构：**

```json
{
  "llm": {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-***",
    "model": "deepseek-chat",
    "roles": {
      "title":    { "provider": "", "base_url": "", "api_key": "", "model": "" },
      "answer":   { "provider": "", "base_url": "", "api_key": "", "model": "" },
      "evaluate": { "provider": "", "base_url": "", "api_key": "", "model": "" },
      "review":   { "provider": "", "base_url": "", "api_key": "", "model": "" },
      "deepen":   { "provider": "", "base_url": "", "api_key": "", "model": "" }
    }
  },
  "tavily_api_key": "tvly-...",
  "feynman_pass_score": 60
}
```

---

### 4.4 DB 配置（config/db.json）

```json
{
  "type": "sqlite",
  "sqlite_path": "~/.aiterate/data.db",
  "host": "127.0.0.1",
  "port": 5432,
  "dbname": "aiterate",
  "user": "geekinney",
  "password": ""
}
```

**安全设计：** Settings UI 中 DB 配置修改采用先测试后保存：先用临时 engine 测试候选配置连接，成功后才落地写入。失败时旧配置不受影响，防止坏配置导致服务崩溃。

---

### 4.5 knowledge_tree.json（知识树）

```json
[
  {
    "id": "cs",
    "title": "计算机",
    "children": [
      { "id": "cs-lang", "title": "编程语言", "children": [...] },
      { "id": "cs-dsa",  "title": "数据结构与算法", "children": [...] }
    ]
  }
]
```

支持领域：计算机、写作、心理学、哲学（4 域，120+ 节点）。知识地图只标记哪些节点被学习过，不追踪进度百分比。

---

## 5. 后端模块

### 5.1 aiterate_server.py

FastAPI 应用主文件，负责：
- 路由注册与参数校验（Pydantic Models）
- **鉴权中间件**：`_require_admin()` 对所有写操作验证 `X-Admin-Token` 头
- **CORS 白名单**：限定 `localhost`/`127.0.0.1`/局域网 IP
- **密钥安全**：`_mask_key()` 掩码 API key；`_safe_llm_dict()` 安全序列化
- **输入限制**：Session 20000 / Deepen 10000 / Feynman 5000 字符上限
- 后台任务调度（`BackgroundTasks`）
- Stale preparing 恢复：启动时自动将超时 preparing session 标记 error
- 静态文件托管（`/assets`）

### 5.2 aiterate_db.py

数据库 CRUD 封装层，设计原则：
- SQLAlchemy Core（非 ORM），统一抽象 SQLite/PG/MySQL/Oracle
- **事务上下文**：`_tx()` 提供 `with` 语法的事务管理，自动 commit/rollback
- **原子操作**：`create_round_with_seq()` 锁 session 行防并发；`create_feynman_group()` / `complete_feynman_group()` 事务化
- **DB 配置安全**：`test_db_config()` 先测候选配置后保存，失败不落盘
- `engine` 切换时 dispose 旧 engine，加锁防并发

### 5.3 aiterate_ai.py

LLM 调用引擎，负责：
- **Prompt 构建**：针对不同角色构建专项 System Prompt
- **多 Provider 路由**：role 级配置 → 全局配置 fallback
- **Tavily 联网搜索**：时效性问题自动触发
- **JSON 鲁棒解析**：`_extract_json_block()` 从 LLM 原始输出中提取 `{}` 或 `[]` 块
- 费曼出题/评分、理解评价（含 gap 提取）、深化追问、标题生成

---

## 6. 前端模块

### 6.1 整体布局

```
┌──────────────────────────────────────────────┐
│  header（AIterate + 知识地图 + 指挥中心 + 设置 + 主题）│
├────────────────┬─────────────────────────────┤
│  sidebar       │  workspace（三 tab）         │
│  ┌──────────┐  │  ┌──────────────────────┐   │
│  │ 统计信息  │  │  │  学习 ←→ 深化 ←→ 费曼 │   │
│  ├──────────┤  │  ├──────────────────────┤   │
│  │ 会话列表  │  │  │  薄弱点面板 + 费曼报告  │   │
│  └──────────┘  │  │  轮次卡片（含 gap）     │   │
│                │  │  输入区（理解/追问）    │   │
└────────────────┴──┴──────────────────────────┘
```

### 6.2 api.js

统一 fetch 封装。所有写操作自动附加 `X-Admin-Token` 头。

### 6.3 app.js

全局入口，负责：
- 初始化 / 会话轮询 / 主题切换
- **知识地图**：4 大领域卡片式展示，展开查看子节点，状态圆点标记学习状态
- **指挥中心**：待完成费曼、今日复习、待修正 session、进行中、推荐节点
- 全局事件监听

### 6.4 workspace.js

工作区核心，负责：
- 三 tab 布局：学习（material）/ 深化（理解+追问+薄弱点）/ 费曼（出题+评分+报告）
- `buildDeepenRoundCard()`：take/press 轮次卡片，含 AI 评价 + gap 展示
- `buildReviewPanel()`：费曼历史记录 + 完成报告（掌握度/强项/弱项/复习建议）
- 薄弱点横幅：汇总所有待解决 gap

### 6.5 settings.js

设置面板（5 tab），支持：
- AI 基础 / 分功能模型 / 联网搜索 / 数据库 / 学习参数
- Provider 预设快速切换
- 密钥掩码显示（`sk-...abcd`），留空不修改
- 每个 LLM 角色独立配置

### 6.6 utils.js

工具函数 + **SVG 图标库**：
- `escapeHtml()` / `renderMarkdown()`（含 DOMPurify 消毒）
- `getStageMeta()` 状态元数据
- `icon(name)` — 17 个 Lucide 风格内联 SVG（book/check/warn/clock/chart/bulb/target/clip/refresh/zap/search/flask/globe/rocket/save/gear/sun/moon/monitor/brain/atom/compass/tag/menu/sparkle）

---

## 7. API 接口

### 系统 & 鉴权

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/healthz` | ✗ | 健康检查 |
| GET | `/api/ready` | ✗ | LLM / Tavily 就绪状态 |
| GET | `/api/stats` | ✗ | 统计数据 |

### Profile & Settings（写操作需鉴权）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/settings` | ✗ | 获取 settings（密钥掩码） |
| PATCH | `/api/settings` | ✓ | 更新 settings（留空不修改） |
| PUT | `/api/db-config` | ✓ | 更新 DB 配置（先测后存） |
| POST | `/api/db-config/test` | ✓ | 测试 DB 连接 |

### Sessions

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/sessions` | ✗ | 会话列表 |
| POST | `/api/sessions` | ✓ | 创建会话，后台 AI 处理 |
| GET | `/api/sessions/{id}/workspace` | ✗ | 工作区数据（含 gap/report） |
| POST | `/api/sessions/{id}/deepen` | ✓ | 提交轮次（take/press） |
| POST | `/api/sessions/{id}/start-feynman` | ✓ | 启动费曼（事务化创建题组） |
| POST | `/api/sessions/{id}/complete-feynman` | ✓ | 提交费曼答案（事务化评分） |

### 知识树 & 指挥中心

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge-tree` | 知识树配置 |
| GET | `/api/knowledge-tree/progress` | 节点学习进度 |
| GET | `/api/command-center` | 指挥中心聚合数据 |

### 复习

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/api/review/{id}/complete` | ✓ | 标记复习完成 |

---

## 8. 学习流程

### 8.1 标准流程

```
1. 用户输入问题/观点 + 选择知识节点
         │
         ▼
2. 创建 session（status=preparing）
   后台 AI 生成 material（正式学习回答）
         │
         ▼
3. session.status = learning
   展示 material + 知识节点标签
         │
         ▼
4. 用户写"理解"→ 提交 take
   AI 评价理解，给出得分 + gaps（薄弱点）
   薄弱点持久化，在深化页集中展示
         │
    ┌────┴──────┐
    │           │
    ▼           ▼
5a. 追问        5b. 费曼自测
  press           start-feynman（事务化出题）
  AI直接回答      用户作答
                  complete-feynman（事务化评分）
         │
         ▼
6. 费曼通过 → completed + 生成学习报告
   （掌握度 / 强项 / 弱项 / 复习建议）
   费曼未通过 → revising（退回深化）
         │
         ▼
7. 自动排期下次复习
   低分 1 天 / 中等 3-5 天 / 高分 7-14 天
   指挥中心展示到期复习 + 逾期标记
```

---

## 9. LLM 配置体系

| Provider | base_url |
|----------|----------|
| deepseek | `https://api.deepseek.com/v1` |
| kimi     | `https://api.moonshot.cn/v1` |
| doubao   | `https://ark.cn-beijing.volces.com/api/v3` |
| copilot  | `https://api.githubcopilot.com` |
| 自定义   | 用户填写 |

Role 优先级：`role 配置（非空） → 全局配置 → 报错`

5 个 LLM 角色：`title`（标题）/ `answer`（材料）/ `evaluate`（理解评价）/ `review`（费曼评分）/ `deepen`（深化追问）

---

## 10. 主题系统

两套 CSS 通过 `<link>` + `data-theme` 属性切换。所有主题规则带 scope 前缀（`[data-theme="night"] .xxx`），避免切换时全局 reflow。移动端 ≤620px 模态框自动全屏铺满（`border-radius: 0; width: 100%; height: 100%`）。

---

## 11. 安全设计

| 措施 | 实现 |
|------|------|
| **Admin Token** | 首次启动随机 UUID，注入 `<script>` 到 index.html，写操作验证 `X-Admin-Token` |
| **密钥掩码** | GET /api/settings 返回 `sk-...abcd`；PATCH 留空不覆盖；`__CLEAR__` 清除 |
| **CORS** | `allow_origins=["http://localhost:*", "http://127.0.0.1:*", "http://192.168.31.*:*"]` |
| **XSS** | DOMPurify 消毒 Markdown 输出，白名单标签+属性，链接协议过滤 |
| **输入限制** | 20000/10000/5000 字符上限（session/deepen/feynman） |
| **DB 安全** | 先测后存，失败不落盘 |
| **并发安全** | 事务化写入、SELECT FOR UPDATE、409 防重复提交 |

---

## 12. 部署说明

### 依赖

```
Python 3.11+
pip install fastapi uvicorn aiohttp python-multipart
```

### 初始化数据库

```bash
python aiterate_db.py   # 自动建表 + 迁移
```

### 启动服务

```bash
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

### 测试

```bash
pytest tests/test_unit.py -q      # 19 个离线单测
python tests/live_full_flow.py    # 全量 AI 回归（消耗额度）
```

### 数据备份

```bash
# SQLite
cp ~/.aiterate/data.db aiterate_backup.db

# PostgreSQL
pg_dump -U geekinney aiterate > aiterate_backup.sql
```

---

*设计文档由 Hermes Agent 根据源码自动生成并维护。*
