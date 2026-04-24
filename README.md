# AIIterate

> AI 迭代学习系统——问题驱动、AI 伴学、费曼验证，完全自托管。

---

## 特性

- **问题驱动学习**：以一个问题或材料为起点，AI 生成正式学习回答
- **多维迭代强化**
  - **理解（Take）**：写下理解，AI 评分 + 深化建议
  - **追问（Press）**：随时追问，AI 直接解答
  - **费曼自测（Feynman）**：AI 出题，用户作答，AI 评分验证掌握程度
- **多 Provider 支持**：DeepSeek / Kimi / 豆包 / GitHub Copilot / 自定义 OpenAI-compatible API
- **角色级 LLM 配置**：标题生成、材料回答、理解评价、追问回答、深化分析——每个角色可独立配置不同模型
- **联网搜索增强**：Tavily API 集成，时效性问题自动触发网络搜索
- **多数据库支持**：SQLite（零配置）/ PostgreSQL / MySQL，通过 UI 设置切换
- **双主题**：暗色（night）/ 亮色（mono）
- **完全自托管**：FastAPI + 纯前端 SPA，数据完全本地

---

## 快速部署

### 方式一：Docker（推荐）

最简单的方式，零依赖，一键启动。

**1. 克隆项目**

```bash
git clone https://github.com/Kinneyzhang/AIterate.git
cd AIterate
```

**2. 准备数据库配置**

```bash
mkdir -p config
cp config/db.json.example config/db.json
```

默认使用 **SQLite**，无需额外配置。`config/db.json` 示例：

```json
{
  "type": "sqlite",
  "sqlite_path": "/data/aiterate.db"
}
```

如需 PostgreSQL，修改为：

```json
{
  "type": "postgresql",
  "host": "postgres",
  "port": 5432,
  "dbname": "aiterate",
  "user": "aiterate",
  "password": "change_me"
}
```

**3. 启动服务**

```bash
docker compose up -d
```

浏览器访问 `http://localhost:7070`，在右上角 ⚙ 设置中填入 LLM API Key 即可使用。

**4. 查看日志**

```bash
docker compose logs -f aiterate
```

**5. 停止 / 重启**

```bash
docker compose down
docker compose restart aiterate
```

---

### 方式二：带 PostgreSQL 的 Docker Compose

取消 `docker-compose.yml` 中 `postgres` 服务的注释，并将 `config/db.json` 中 `host` 改为 `postgres`（容器间网络名）：

```bash
# 先启动 PG，再启动 aiterate
docker compose up -d postgres
sleep 5
docker compose up -d aiterate
```

---

### 方式三：直接运行（裸机）

**依赖**

```
Python 3.11+
```

可选（根据数据库类型安装驱动）：

| 数据库 | 额外依赖 |
|--------|----------|
| SQLite | 无（Python 内置） |
| PostgreSQL | `psycopg2-binary` |
| MySQL | `pymysql` |

**安装**

```bash
pip install -r requirements.txt
```

**配置数据库**

```bash
cp config/db.json.example config/db.json
# 编辑 config/db.json，填写数据库连接信息
```

**启动**

```bash
# 初始化数据库表
python aiterate_db.py

# 启动服务
uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
```

---

### 方式四：systemd 服务（Linux 长期运行）

```bash
# 以用户服务方式运行（不需要 root）
cat > ~/.config/systemd/user/aiterate.service << 'EOF'
[Unit]
Description=AIIterate Learning System
After=network.target

[Service]
WorkingDirectory=/path/to/AIterate
ExecStart=/usr/bin/python3 -m uvicorn aiterate_server:app --host 0.0.0.0 --port 7070
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now aiterate
```

---

## 配置说明

### LLM 配置

通过页面右上角 **⚙ 设置** 进行配置，无需修改任何文件。配置项：

| 配置 | 说明 |
|------|------|
| Provider | 预设：deepseek / kimi / 豆包 / copilot / 自定义 |
| Base URL | API 地址（选预设后自动填充） |
| API Key | 对应 provider 的密钥 |
| 默认模型 | 全局默认模型 |
| 角色模型 | 各功能独立配置（可选，不填则用默认） |

### 数据库配置

通过 **⚙ 设置 → 数据库** 页面切换，支持：

- **SQLite**：开箱即用，适合个人使用
- **PostgreSQL**：适合多用户 / 高可用部署
- **MySQL**：需额外安装 `pymysql`

配置保存在 `config/db.json`（不入 git，不含密码上传）。

### Tavily 联网搜索（可选）

在 **⚙ 设置 → 联网搜索** 中填入 [Tavily API Key](https://tavily.com)，时效性问题将自动触发网络搜索增强。

---

## 架构概览

```
Browser (SPA)
    │ HTTP/REST
FastAPI (aiterate_server.py)
    ├── aiterate_db.py   — SQLAlchemy Core CRUD（sqlite/pg/mysql）
    └── aiterate_ai.py   — LLM 调用 / Prompt / Tavily 搜索
              │
         Database（SQLite / PostgreSQL / MySQL）
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
| 数据库 | SQLite / PostgreSQL / MySQL（SQLAlchemy Core） |
| AI 调用 | OpenAI-compatible REST API（aiohttp 异步） |
| 字体 | LXGW WenKai Screen（霞鹜文楷屏幕版） |

---

## License

MIT
