#!/usr/bin/env bash
# 启动内置 PostgreSQL（ zonky arm64 独立二进制，数据在 .pg/data ）
set -e
PG_DIR="$(cd "$(dirname "$0")/.." && pwd)/.pg"

if [ ! -d "$PG_DIR/data" ]; then
  echo "初始化数据库集群..."
  "$PG_DIR/bin/initdb" -D "$PG_DIR/data" -U postgres --auth=trust --encoding=UTF8
fi

# Unix socket 放 /tmp（某些挂载点不允许创建 socket 文件）
"$PG_DIR/bin/pg_ctl" -D "$PG_DIR/data" -l "$PG_DIR/pg.log" -o "-p 5432 -k /tmp" start

python3 - <<'PY'
import psycopg
with psycopg.connect(host='127.0.0.1', port=5432, user='postgres',
                     dbname='postgres', autocommit=True) as c:
    exists = c.execute("SELECT 1 FROM pg_database WHERE datname='laytime'").fetchone()
    if not exists:
        c.execute('CREATE DATABASE laytime')
        print('database laytime created')
print('PostgreSQL 就绪: 127.0.0.1:5432')
PY
