# 装卸时间与滞期速遣核算（演示系统）

从事实时间表计算装卸允许时间及滞期/速遣费用。**全部租约条款为虚构，仅用于演示计时与费用核算，不构成法律解释或建议。**

## 架构

```
backend/   Django 5 + DRF，计算引擎全部使用 Decimal
frontend/  React 18 + Vite（开发服务器代理 /api 到 :8000）
数据库     生产 PostgreSQL（DB_* 环境变量切换），本地默认 SQLite
```

## 核心设计

**三种时间严格分开**（`backend/laytime/engine.py`）

| 概念 | 定义 |
|---|---|
| 自然时间 | NOR 被接受 → 装卸完毕的挂钟时间 |
| 允许计入时间 | 自然时间 − 可排除区间（周末/天气/等泊），重叠原因按**区间并集**只扣一次 |
| 实际作业时间 | 自然时间 − 全部停工区间 |

**事实与证据**

- `EventFragment` 记录抵港、NOR 送达、NOR 被接受、停工/复工（含原因）、装卸完毕。
- **NOR 送达与 NOR 被接受是不同事件类型**：只有被接受才起算（虚构条款 CP-01）；只送达未接受的航次结算状态为 `BLOCKED`。
- 缺证据的片段 `evidence_status=PENDING`，不参与核算，在结算中列为待核对；补齐证据（PATCH 为 VERIFIED）后重新核算即生效。

**排除规则按条款判断**

- CP-02 周末（默认周六 00:00 – 周一 00:00，参数化于 `Clause.parameters`，按项目本地时区判定）
- CP-03 天气停工、CP-04 等泊：由停工片段的原因驱动
- CP-05 重叠不重复扣减：引擎先把时间轴切成基本区间，再对每个区间取「活跃原因集合」，从结构上保证并集扣减

**可追溯与不可变**

- 每笔费用（`SettlementLine`）保存：金额、计时基数（小时）、费率、采用条款代码、以及推导它的**完整区间列表**——财务可从任何一笔费用追到计时区间与条款。
- `Settlement` 只增不改：重新核算插入 `version+1` 新行；API 层只读（PUT/PATCH/DELETE 返回 405），`(voyage, version)` 唯一约束兜底。历史结算永不被覆盖。

## 演示案例（`python manage.py seed_demo`）

| 案例 | 场景 | 结果 |
|---|---|---|
| A | 跨午夜天气停工 22:00→02:00，另有一条待核对停工片段 | 自然 28h − 4h = 计入 24h，允许 20h → 滞期费 2,000.00；待核对片段不参与 |
| B | 天气 10:00–14:00 与等泊 12:00–16:00 交叠 | 并集 10:00–16:00 只扣 6h（非 8h）→ 计入 30h，允许 28h → 滞期费 1,000.00 |
| C | 横跨周末且刚好用尽 | 自然 72h − 周末 48h = 计入 24h = 允许 24h → 滞期/速遣均为 0 |
| D | NOR 已送达但未被接受 | `BLOCKED`，无法起算 |

## 运行

```bash
# 后端
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py test          # 7 个测试覆盖上述案例与不可变性
python manage.py runserver

# 前端（另开终端）
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

生产数据库（PostgreSQL）通过环境变量切换：

```bash
export DB_ENGINE=django.db.backends.postgresql DB_NAME=laytime \
       DB_USER=laytime DB_PASSWORD=*** DB_HOST=127.0.0.1 DB_PORT=5432
```

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/voyages/` | 航次列表（含条款） |
| GET | `/api/voyages/{id}/timeline/` | 事件片段 + 最新结算 |
| POST | `/api/voyages/{id}/calculate/` | 核算并写入**新版本**结算 |
| GET | `/api/settlements/?voyage={id}` | 结算历史（只读） |
| GET/POST/PATCH | `/api/fragments/` | 事件片段；可补证据后改状态，不可删除 |
