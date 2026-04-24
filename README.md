<div align="center">

# 🧠 AIIterate

**AI 迭代学习系统 · 问题驱动 · AI 全程伴学 · 费曼验证**

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
  - [LLM 配置](#llm-配置)
  - [数据库配置](#数据库配置)
  - [联网搜索](#联网搜索可选)
- [架构概览](#-架构概览)
- [项目结构](#-项目结构)
- [技术栈](#-技术栈)
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
| 🤔 **理解评分（Take）** | 写下你的理解，AI 给出评分 + 深化建议 |
| ❓ **追问深化（Press）** | 随时追问疑点，AI 直接解答 |
| 🎓 **费曼自测（Feynman）** | AI 出多道考题，用户作答，AI 逐题评分，低于 60 分退回重学 |
| 🌲 **知识树管理** | 计算机 / 写作 / 心理学 / 哲学四大领域，支持自定义扩展 |

### 技术能力
| 功能 | 说明 |
|------|------|
| 🤖 **多 Provider 支持** | DeepSeek / Kimi / 豆包 / GitHub Copilot / 任意 OpenAI-compatible API |
| 🎭 **角色级 LLM 配置** | 标题生成、材料回答、评价、追问、深化——每个角色可用不同模型 |
| 🌐 **联网搜索增强** | Tavily API 集成，时效性问题自动触发实时搜索 |
| 🗄️ **多数据库支持** | SQLite（零配置）/ PostgreSQL / MySQL，UI 中切换无需重启 |
| 🎨 **双主题** | 暗色（night）/ 亮色（mono），无抖动切换 |
| 🏠 **完全自托管** | 所有数据本地存储，无任何外部依赖或数据上传 |

---

## 🔄 学习流程

```
┌─────────────────────────────────────────────────────────────────┐
│  ① 输入问题                                                        │
│     └─→ AI 生成学习材料（status: preparing → learning）            │
│                                                                  │
│  ② 阅读 + 写理解                                                   │
│     └─→ AI 评分 + 给出深化方向（status: deepening）                │
│                                                                  │
│  ③ 追问 / 深化（可选，多轮）                                        │
│     └─→ AI 直接解答追问                                            │
│                                                                  │
│  ④ 费曼自测                                                        │
│     └─→ AI 出题（3～5道）→ 用户作答 → AI 逐题评分                   │
│         ├── 平均分 ≥ 60  →  completed ✅                          │
│         └── 平均分 < 60  →  revising（退回重学）🔁                 │
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

打开浏览器访问 `http://localhost:7070`，点击右上角 ⚙ **设置**，填入你的 LLM API Key，即可开始学习。

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
# 创建 systemd 用户服务（无需 root 权限）
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

# 替换实际路径
# WorkingDirectory 和 ExecStart 中的路径请修改为实际安装目录和 Python 路径

systemctl --user daemon-reload
systemctl --user enable --now aiterate

# 查看状态
systemctl --user status aiterate
journalctl --user -u aiterate -f
```

---

## ⚙ 配置指南

所有配置通过页面右上角 **⚙ 设置** 完成，无需修改任何配置文件。

### LLM 配置

进入 **设置 → AI 基础配置**：

| 字段 | 说明 |
|------|------|
| Provider | 选择预设（deepseek / kimi / 豆包 / copilot）或选「自定义」手动填 Base URL |
| Base URL | API 地址，选预设后自动填充 |
| API Key | 对应 Provider 的密钥 |
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

进入 **设置 → 数据库**，支持三种数据库：

**SQLite**（推荐个人使用）
```
文件路径：/data/aiterate.db（Docker 内路径，对应宿主机 ./data/）
```

**PostgreSQL**
```
Host / Port / 数据库名 / 用户名 / 密码
```

**MySQL**
```
Host / Port / 数据库名 / 用户名 / 密码
```

> 切换数据库后点击保存，服务会自动重连，**无需重启**。
>
> ⚠️ 注意：切换数据库不会迁移历史数据，请提前做好备份。

### 联网搜索（可选）

进入 **设置 → 联网搜索**，填入 [Tavily API Key](https://app.tavily.com)。

启用后，系统会自动判断问题是否具有时效性（如"最新版本"、"今年"等），并触发实时网络搜索，将搜索结果作为上下文注入 AI 回答。

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
└──────────┬──────────────────────┬───────────────────┘
           │                      │
┌──────────▼──────────┐  ┌────────▼──────────────────┐
│   aiterate_db.py    │  │      aiterate_ai.py        │
│  SQLAlchemy Core    │  │  LLM 调用 / Prompt 构建     │
│  多数据库 CRUD 封装   │  │  Tavily 联网搜索            │
└──────────┬──────────┘  └────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────┐
│            Database（SQLite / PG / MySQL）           │
│              sessions  /  rounds  /  profile        │
└─────────────────────────────────────────────────────┘
```

**数据模型简述：**

- `sessions` — 每个学习会话（topic、status、stage、type 等）
- `rounds` — 会话下的每一轮交互（take/press/feynman，含 input/output/score）
- `profile` — 系统配置（LLM 设置、主题、知识树等）

---

## 📁 项目结构

```
AIterate/
├── index.html                  # SPA 入口
├── aiterate_server.py          # FastAPI 路由层
├── aiterate_db.py              # 数据库 CRUD（SQLAlchemy Core）
├── aiterate_ai.py              # LLM 调用 / Prompt / Tavily
├── aiterate_flow.py            # 流程辅助模块
├── requirements.txt            # Python 依赖
├── Dockerfile                  # Docker 镜像构建
├── docker-compose.yml          # Docker Compose 编排
├── config/
│   ├── db.json                 # 数据库配置（gitignored，含密码）
│   └── db.json.example         # 配置模板（入库）
├── assets/
│   ├── app.css                 # 全局基础样式
│   ├── themes/
│   │   ├── night.css           # 暗色主题
│   │   └── mono.css            # 亮色主题
│   └── js/
│       ├── app.js              # 主入口，状态协调
│       ├── api.js              # 所有 HTTP 请求封装
│       ├── sidebar.js          # 左侧会话列表
│       ├── workspace.js        # 右侧工作区（学习主界面）
│       ├── settings.js         # 设置弹窗（4 个 tab）
│       └── utils.js            # 常量 / 工具函数
├── tests/                      # 测试脚本
└── DESIGN.md                   # 详细系统设计文档
```

---

## 🛠 技术栈

| 层次 | 技术选型 | 说明 |
|------|----------|------|
| 前端 | 原生 HTML / CSS / JavaScript | 无框架 SPA，零构建步骤 |
| 后端 | Python 3.11 + FastAPI | 异步路由，后台任务调度 |
| 数据库 | SQLAlchemy Core | 统一抽象层，支持 SQLite / PG / MySQL |
| AI 调用 | aiohttp | 异步 HTTP，OpenAI-compatible API |
| 搜索增强 | Tavily API | 实时网络搜索，结构化结果 |
| 字体 | LXGW WenKai Screen | 霞鹜文楷屏幕版，subset 分片加载 |
| 容器化 | Docker + Compose | 一键部署，数据持久化 |

---

## 👩‍💻 开发与贡献

**本地开发启动：**

```bash
git clone https://github.com/Kinneyzhang/AIterate.git
cd AIterate

pip install -r requirements.txt
cp config/db.json.example config/db.json
# 编辑 config/db.json

python aiterate_db.py
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070 --reload
```

`--reload` 开启热重载，修改 Python 文件后自动重启。

前端文件（HTML/CSS/JS）修改后**刷新浏览器**即可生效，无需重启服务。

**详细设计文档：** [DESIGN.md](./DESIGN.md)

---

## 📄 License

[MIT](LICENSE) © Kinneyzhang
