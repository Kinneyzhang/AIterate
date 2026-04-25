<div align="center">

# 🧠 AIIterate

**AI 迭代学习系统 · 问题驱动 · AI 全程伴学 · 费曼验证**

[![Vue](https://img.shields.io/badge/Vue-3.x-4FC08D.svg)](https://vuejs.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](Dockerfile)

*一个以「提出问题」为起点，以「费曼自测」为终点的个人 AI 学习操作系统。完全自托管，数据本地。*

</div>

---

## 📖 目录

- [核心理念](#-核心理念)
- [功能特性](#-功能特性)
- [学习流程](#-学习流程)
- [快速开始](#-快速开始)
  - [方式一：Docker（推荐）](#方式一docker推荐)
  - [方式二：Docker + PostgreSQL](#方式二docker--postgresql)
  - [方式三：裸机运行](#方式三裸机运行)
  - [方式四：systemd 服务](#方式四systemd-服务)
- [配置指南](#-配置指南)
- [架构概览](#-架构概览)
- [项目结构](#-项目结构)
- [技术栈](#-技术栈)
- [安全设计](#-安全设计)
- [开发与贡献](#-开发与贡献)
- [License](#-license)

---

## 💡 核心理念

传统学习工具要么是被动的笔记仓库，要么是单次问答的 AI 对话。**AIIterate** 的设计出发点是：

> **真正的掌握 = 主动理解 + 反复迭代 + 可验证的输出**

核心循环基于**费曼学习法**——你能清晰地向别人解释一件事，才算真正学会它。

系统将每次学习拆解为严格的状态机流转：

```
提出问题 → AI 生成材料 → 阅读理解 → 写下理解/AI 评分
    → 追问深化 → 费曼自测（AI 出题 + 评分） → 完成
```

每个环节 AI 全程参与，但**主动权始终在学习者手中**。

---

## ✨ 功能特性

### 学习核心

| 功能 | 说明 |
|------|------|
| 📝 **AI 材料生成** | 输入问题，AI 自动生成结构化学习材料 |
| 🤔 **理解评分（Take）** | 写下你的理解，AI 给出评分 + 薄弱点定位 |
| ❓ **追问深化（Press）** | 随时追问疑点，AI 直接解答 |
| 🎓 **费曼自测（Feynman）** | AI 出多道考题，逐题评分，低于及格线退回重学 |
| 🗺️ **知识地图** | 计算机/写作/心理学/哲学四大领域，卡片式展示已学知识点 |
| 🎯 **指挥中心** | 待完成费曼、今日复习、待修正 session 一览 |
| 📋 **薄弱点追踪** | 每次理解评价提取 gap，持久化并在深化页集中展示 |
| 📊 **学习报告** | 费曼完成后生成掌握度/强项/弱项/复习建议报告 |
| 🔁 **间隔复习** | 完成 session 后自动排期下次复习，逾期高亮提醒 |

### 技术能力

| 功能 | 说明 |
|------|------|
| 🤖 **多 Provider 支持** | DeepSeek / Kimi / 豆包 / GitHub Copilot / 任意 OpenAI-compatible API |
| 🎭 **角色级 LLM 配置** | 标题生成、材料回答、评价、追问、深化——每个角色可独立配置模型 |
| 🌐 **联网搜索增强** | Tavily API 集成，时效性问题自动触发实时搜索 |
| 🗄️ **多数据库支持** | SQLite（零配置）/ PostgreSQL / MySQL，UI 中切换无需重启 |
| 🎨 **双主题** | 暗色（night）/ 亮色（mono），无抖动切换 |
| 🏠 **完全自托管** | 所有数据本地存储，无任何外部依赖或数据上传 |
| 🔐 **安全加固** | Admin token 鉴权、密钥掩码、DOMPurify XSS 防护、CORS 白名单 |

---

## 🔄 学习流程

```
┌─────────────────────────────────────────────────────────────────┐
│  ① 输入问题                                                        │
│     └─→ AI 生成学习材料（status: preparing → learning）            │
│                                                                  │
│  ② 阅读 + 写理解                                                   │
│     └─→ AI 评分 + 定位薄弱点（status: deepening）                  │
│                                                                  │
│  ③ 追问 / 深化（可选，多轮）                                        │
│     └─→ AI 直接解答追问 + 持续定位薄弱点                            │
│                                                                  │
│  ④ 费曼自测                                                        │
│     └─→ AI 出题（3～5道）→ 用户作答 → AI 逐题评分                   │
│         ├── 平均分 ≥ 60  →  completed ✅ + 生成学习报告             │
│         └── 平均分 < 60  →  revising（退回重学）🔁                 │
│                                                                  │
│  ⑤ 复习计划                                                        │
│     └─→ 自动排期下次复习（低分 1 天 / 中等 3-5 天 / 高分 7-14 天）  │
└─────────────────────────────────────────────────────────────────┘
```

**会话状态说明：**

| 状态 | 含义 |
|------|------|
| `preparing` | AI 正在生成学习材料 |
| `learning` | 材料已就绪，等待用户阅读 |
| `deepening` | 用户提交理解，AI 正在评分/深化 |
| `revising` | 费曼未通过，退回重新巩固 |
| `feynman` | 费曼自测进行中 |
| `completed` | 费曼通过，学习完成 |
| `error` | 发生错误 |

---

## 🚀 快速开始

### 方式一：Docker（推荐）

最简单的方式。使用 SQLite，无需安装数据库，一条命令启动。

**1. 克隆项目**

```bash
git clone https://github.com/Kinneyzhang/AIterate.git
cd AIterate
```

**2. 准备配置**

```bash
mkdir -p config
cp config/db.json.example config/db.json
```

默认 `config/db.json` 使用 SQLite，无需修改：

```json
{
  "type": "sqlite",
  "sqlite_path": "/data/aiterate.db"
}
```

**3. 启动**

```bash
docker compose up -d
```

**4. 访问**

打开浏览器访问 `http://localhost:7070`，点击右上角设置按钮，填入你的 LLM API Key，即可开始学习。

**常用命令：**

```bash
# 查看实时日志
docker compose logs -f aiterate

# 重启服务
docker compose restart aiterate

# 停止服务
docker compose down

# 更新到最新版本
git pull
docker compose build --no-cache
docker compose up -d
```

> 💾 **数据持久化**：容器数据挂载在项目目录下的 `./data/`，删除容器不会丢失数据。

---

### 方式二：Docker + PostgreSQL

适合多用户或需要更高性能的场景。

**1. 编辑 `docker-compose.yml`**，取消 `postgres` 服务的注释：

```yaml
services:
  aiterate:
    build: .
    ports:
      - "7070:7070"
    volumes:
      - ./config:/app/config
    depends_on:
      - postgres

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: aiterate
      POSTGRES_USER: aiterate
      POSTGRES_PASSWORD: your_password_here
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  pg_data:
```

**2. 更新 `config/db.json`**：

```json
{
  "type": "postgresql",
  "host": "postgres",
  "port": 5432,
  "dbname": "aiterate",
  "user": "aiterate",
  "password": "your_password_here"
}
```

**3. 启动**

```bash
docker compose up -d
```

---

### 方式三：裸机运行

**系统要求：** Python 3.11+

**1. 克隆并安装依赖**

```bash
git clone https://github.com/Kinneyzhang/AIterate.git
cd AIterate
pip install -r requirements.txt
```

根据数据库类型，额外安装驱动：

| 数据库 | 命令 |
|--------|------|
| SQLite | 无需安装（Python 内置） |
| PostgreSQL | `pip install psycopg2-binary` |
| MySQL | `pip install pymysql` |

**2. 配置数据库**

```bash
cp config/db.json.example config/db.json
# 编辑 config/db.json，填写你的数据库信息
```

**3. 初始化数据库**

```bash
python aiterate_db.py
```

**4. 启动服务**

```bash
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

访问 `http://localhost:7070` 即可使用。

---

### 方式四：systemd 服务

适合在 Linux 服务器上长期运行，开机自启，自动重启。

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/aiterate.service << EOF
[Unit]
Description=AIIterate Learning System
After=network.target

[Service]
WorkingDirectory=/path/to/AIterate
ExecStartPre=/path/to/python aiterate_db.py
ExecStart=/path/to/python -m uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now aiterate
```

---

## ⚙ 配置指南

所有配置通过页面右上角设置入口完成，无需修改任何配置文件。

### LLM 配置

进入 **设置 → AI 基础配置**：

| 字段 | 说明 |
|------|------|
| Provider | 选择预设（deepseek / kimi / 豆包 / copilot）或选「自定义」手动填 Base URL |
| Base URL | API 地址，选预设后自动填充 |
| API Key | 对应 Provider 的密钥（已配置时显示为掩码，留空不修改） |
| 默认模型 | 全局默认，各角色未单独配置时使用此模型 |

**预设 Provider 信息：**

| Provider | Base URL |
|----------|----------|
| DeepSeek | `https://api.deepseek.com/v1` |
| Kimi | `https://api.moonshot.cn/v1` |
| 豆包 | `https://ark.cn-beijing.volces.com/api/v3` |
| GitHub Copilot | `https://api.githubcopilot.com` |

进入 **设置 → 分功能模型配置**，可为每个角色单独指定模型（留空则使用默认模型）：

| 角色 | 用途 |
|------|------|
| title | 会话标题生成 |
| answer | 学习材料生成 |
| evaluate | 理解评分 |
| review | 费曼评分 |
| deepen | 深化分析与追问解答 |

### 数据库配置

进入 **设置 → 数据库**，支持三种数据库。切换后点击保存，服务自动重连，无需重启。

> ⚠️ 切换数据库不会迁移历史数据，请提前做好备份。

### 联网搜索（可选）

进入 **设置 → 联网搜索**，填入 [Tavily API Key](https://app.tavily.com)。启用后系统自动判断问题时效性并触发实时搜索。

---

## 🏗 架构概览

```
┌─────────────────────────────────────────────────────┐
│                   Browser (SPA)                     │
│  index.html + assets/js/*.js + assets/css/*.css     │
└────────────────────────┬────────────────────────────┘
                         │ HTTP / REST API
┌────────────────────────▼────────────────────────────┐
│            FastAPI  (aiterate_server.py)             │
│         路由 / 参数校验 / 后台任务调度                  │
│         鉴权 (_require_admin) / CORS 白名单           │
└──────────┬──────────────────────┬───────────────────┘
           │                      │
┌──────────▼──────────┐  ┌────────▼──────────────────┐
│   aiterate_db.py    │  │      aiterate_ai.py        │
│  SQLAlchemy Core    │  │  LLM 调用 / Prompt 构建     │
│  多数据库 CRUD 封装   │  │  Tavily 联网搜索            │
│  事务化写入           │  │  JSON 鲁棒解析             │
└──────────┬──────────┘  └────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────┐
│            Database（SQLite / PG / MySQL）           │
│   sessions / rounds / review_reports / profile      │
└─────────────────────────────────────────────────────┘
```

---

## 📁 项目结构

```
AIterate/
├── index.html                  # SPA 入口
├── aiterate_server.py          # FastAPI 路由层（含鉴权）
├── aiterate_db.py              # 数据库 CRUD（SQLAlchemy Core，事务化）
├── aiterate_ai.py              # LLM 调用 / Prompt / Tavily
├── requirements.txt            # Python 依赖
├── Dockerfile                  # Docker 镜像构建
├── docker-compose.yml          # Docker Compose 编排
├── config/
│   ├── db.json                 # 数据库配置（gitignored，含密码）
│   ├── db.json.example         # 配置模板（入库）
│   └── knowledge_tree.json     # 知识树领域定义
├── assets/
│   ├── app.css                 # 全局基础样式
│   ├── fonts.css               # 字体声明
│   ├── themes/
│   │   ├── night.css           # 暗色主题
│   │   └── mono.css            # 亮色主题
│   └── js/
│       ├── app.js              # 主入口，状态协调，知识地图，指挥中心
│       ├── api.js              # 所有 HTTP 请求封装
│       ├── sidebar.js          # 左侧会话列表
│       ├── workspace.js        # 右侧工作区（学习/深化/费曼三 tab）
│       ├── modal.js            # 新建 session 弹窗 + 知识节点推荐
│       ├── settings.js         # 设置弹窗（5 个 tab）
│       └── utils.js            # 工具函数 + SVG 图标库
├── tests/
│   ├── conftest.py             # pytest 配置
│   ├── test_unit.py            # 19 个离线单测（CI 稳定）
│   └── live_full_flow.py       # 全量 AI 回归测试（手动运行）
├── README.md
└── DESIGN.md                   # 详细系统设计文档
```

---

## 🛠 技术栈

| 层次 | 技术选型 | 说明 |
|------|----------|------|
| 前端 | Vue 3 + Vue Router（ES Module，零构建） | 响应式 SPA，CompAPI，importmap 加载 |
| 后端 | Python 3.11 + FastAPI | 异步路由，后台任务调度 |
| 数据库 | SQLAlchemy Core | 统一抽象层，SQLite / PG / MySQL |
| AI 调用 | aiohttp | 异步 HTTP，OpenAI-compatible API |
| 搜索增强 | Tavily API | 实时网络搜索，结构化结果 |
| 安全 | DOMPurify + Admin Token | XSS 防护，接口鉴权 |
| 图标 | 内联 SVG | 17 个 Lucide 风格图标，全平台一致 |
| 字体 | LXGW WenKai Screen | 霞鹜文楷屏幕版，subset 分片加载 |
| 容器化 | Docker + Compose | 一键部署，数据持久化 |

---

## 🔐 安全设计

| 措施 | 说明 |
|------|------|
| **Admin Token** | 首次启动自动生成 UUID token 注入 HTML，写操作需 `X-Admin-Token` 头 |
| **密钥掩码** | API Key 返回 `sk-...abcd`，前端留空表示不修改，`__CLEAR__` 清除 |
| **CORS 白名单** | 限定 `localhost` + `127.0.0.1` + 局域网 IP，非 `*` 通配 |
| **XSS 防护** | DOMPurify 消毒 AI 输出 Markdown，白名单标签和属性 |
| **输入限制** | Session 20000 / Deepen 10000 / Feynman 5000 字符上限 |
| **DB 配置安全** | 先测试候选配置再保存，防止坏配置落盘导致服务崩溃 |

---

## 👩‍💻 开发与贡献

**本地开发启动：**

```bash
git clone https://github.com/Kinneyzhang/AIterate.git
cd AIterate

pip install -r requirements.txt
cp config/db.json.example config/db.json
python aiterate_db.py
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070 --reload
```

**运行测试：**

```bash
# 离线单测（CI 稳定）
pytest tests/test_unit.py -q

# 全量 AI 回归（消耗额度，手动运行）
python tests/live_full_flow.py
```

**详细设计文档：** [DESIGN.md](./DESIGN.md)

---

## 📄 License

[MIT](LICENSE) © Kinneyzhang
