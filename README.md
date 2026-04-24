# AIIterate

> AI 迭代学习系统——问题驱动、AI 伴学、费曼验证，完全自托管。

---

## 特性

- **问题驱动学习**：以一个问题或材料为起点，AI 生成正式学习回答
- **多维迭代强化**：
  - **理解（Take）**：写下理解，AI 评分 + 深化建议
  - **追问（Press）**：随时追问，AI 直接解答
  - **费曼自测（Feynman）**：AI 出题，用户作答，AI 评分验证掌握程度
- **多 Provider 支持**：DeepSeek / Kimi / 豆包 / GitHub Copilot / 自定义 OpenAI-compatible API
- **角色级 LLM 配置**：标题生成、材料回答、理解评价、追问回答、深化分析——每个角色可独立配置不同模型
- **联网搜索增强**：Tavily API 集成，时效性问题自动触发网络搜索
- **知识树管理**：计算机 / 写作 / 心理学 / 哲学四大领域，支持自定义扩展
- **双主题**：暗色（night）/ 亮色（mono）主题，无抖动切换
- **完全自托管**：FastAPI + PostgreSQL，数据完全本地

---

## 快速开始

### 依赖

```
Python 3.11+
PostgreSQL 14+
```

```bash
pip install fastapi uvicorn psycopg2-binary aiohttp python-multipart
```

### 启动

```bash
# 1. 初始化数据库
python aiterate_db.py

# 2. 启动服务
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

浏览器访问 `http://localhost:7070`，在设置中填入 LLM API Key 即可使用。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AITERATE_PG_HOST` | `127.0.0.1` | PostgreSQL 主机 |
| `AITERATE_PG_PORT` | `5432` | PostgreSQL 端口 |
| `AITERATE_PG_DBNAME` | `aiterate` | 数据库名 |
| `AITERATE_PG_USER` | `geekinney` | 数据库用户 |
| `AITERATE_PG_PASSWORD` | — | 数据库密码 |

---

## 架构概览

```
Browser (SPA)
    │ HTTP/REST
FastAPI (aiterate_server.py)
    ├── aiterate_db.py   — PostgreSQL CRUD
    └── aiterate_ai.py   — LLM 调用 / Prompt 构建 / Tavily 搜索
              │
         PostgreSQL
    sessions / rounds / profile
```

详细设计见 [DESIGN.md](./DESIGN.md)。

---

## 学习流程

```
输入问题 → AI 生成材料 → 阅读学习
    → 写理解 → AI 评分
    → 追问深化 → AI 解答
    → 费曼自测 → AI 出题 + 评分
    → 完成会话
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 前端 | 原生 HTML/CSS/JS（无框架 SPA） |
| 后端 | Python 3.11 + FastAPI |
| 数据库 | PostgreSQL |
| AI 调用 | OpenAI-compatible REST API（aiohttp 异步） |
| 字体 | LXGW WenKai Screen（霞鹜文楷屏幕版） |

---

## License

MIT
