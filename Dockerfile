FROM python:3.11-slim

WORKDIR /app

# 系统依赖（psycopg2 编译需要 libpq）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 数据目录（SQLite 模式时挂载）
RUN mkdir -p /data

EXPOSE 7070

# 启动：先初始化 DB，再启动服务
CMD ["sh", "-c", "python aiterate_db.py && uvicorn aiterate_server:app --host 0.0.0.0 --port 7070"]
