# 装卸时间与滞期速遣核算系统

从**事实时间表**（Statement of Facts）计算装卸允许时间（Laytime）及**滞期费 / 速遣费**的全栈演示系统。

- **React**：呈现事件片段、停工原因、合同条款与可追溯的核算报告
- **Django REST Framework**：核算引擎，金额一律使用 `Decimal`
- **PostgreSQL**：保存抵港、准备就绪通知（NOR）、停工原因、费率与结算快照

> ⚠️ **声明**：系统内置的 FICTCON-2026 租约为**虚构规则**，仅用于演示计算逻辑，
> 不替代任何真实租约文本或法律解释。

---

## 领域规则（虚构租约 FICTCON-2026）

| 条款 | 内容 |
| --- | --- |
| FIC-01 | 允许装卸时间：装卸合计 72 连续小时 |
| FIC-02 | 起算：NOR **被接受**后 6 小时 |
| FIC-03 | 恶劣天气停工：**不计入** |
| FIC-04 | 周末/节假日停工：**不计入** |
| FIC-05 | 等待泊位：**照计**（不排除） |
| FIC-06 | 船舶设备故障：**照计**（不排除） |
| FIC-07 | 滞期费率：USD 12,000 / 天（不足一天按比例） |
| FIC-08 | 速遣费率：USD 6,000 / 天 |
| FIC-09 | 一旦滞期，持续滞期（用尽后排除不再适用） |

条款以 `Clause` 模型存库（`clause_type` + `params`），每个航次可挂不同租约；
排除与否完全由条款驱动，而非硬编码。

## 核心设计

### 三类时间分开

| 概念 | 定义 |
| --- | --- |
| 自然时间 | 起算点 → 完工 的全部流逝时间 |
| 实际作业时间 | 自然时间 − **全部**停工并集（无论条款是否排除） |
| 允许计入时间（已用） | 自然时间 − **条款排除**的停工并集 |

### 事实与证据

- NOR「送达」(`NOR_TENDERED`) 与「被接受」(`NOR_ACCEPTED`) 是**不同事实**，分别存一行；
  起算只认被接受。只有送达没有接受 → 计算 `BLOCKED`。
- 每个事件/停工都有证据状态：`已核实 / 待核对 / 有争议`。
  含未核实片段时结果标记 `PROVISIONAL`（可试算，**不能定稿**）。

### 重叠不重复扣减

所有停工区间先按条款过滤，再做**区间并集**（`merge_intervals`），
合并时保留全部贡献者（停工记录 id、原因、条款号），
重叠部分只扣一次且可追溯。

### 一旦滞期，持续滞期（可选条款）

引擎按时间轴推进：允许时间用尽的瞬间（`exhaustion_at`）之后，
排除条款不再适用，全部时间计为滞期。边界情形：
允许时间**刚好用尽**（用尽点 == 完工点）时，滞期与速遣均为 0。

### 金额用 Decimal

时间内部以整数秒累计，费用 = `秒数 × 日费率 ÷ 86400`，
全程 `Decimal`，最终 `ROUND_HALF_UP` 到分。绝无浮点误差。

### 可追溯

每笔费用带 `trace`：计时区间、费率条款、允许时间条款、滞期规则条款、计算式；
每条排除带：原因、条款号、来源停工记录 id。

### 历史结算不可覆盖

- 每次结算生成**新版本快照**（`version` 递增），完整报告存入 `report` JSON；
- 草稿可定稿；定稿时旧定稿自动转为「已被取代」（**不删除、不修改**）；
- 已定稿/历史版本：模型层禁止修改任何字段、禁止删除（API 返回 400）。

## 演示案例（`seed_demo`）

| 航次 | 场景 | 结果 |
| --- | --- | --- |
| VOY-DEMO-001 | **跨午夜**：NOR 18:00 被接受 +6h → 午夜 00:00 起算；天气停工 22:00→次日 02:00 | 速遣 USD 4,000.00 |
| VOY-DEMO-002 | **多原因交叠**：天气 10:00–14:00（排除）与设备故障 12:00–16:00（照计）重叠 2h，并集只扣一次 | 滞期 USD 10,000.00 |
| VOY-DEMO-003 | **刚好用尽**：已用恰好 72.0000 小时 | 无滞期无速遣 |
| VOY-DEMO-004 | **待核对**：NOR 被接受与天气停工均缺证据 | `PROVISIONAL`，定稿被拒 |

## 快速开始

```bash
# 1. PostgreSQL（本仓库内置 arm64 独立二进制于 .pg/，或自行准备实例）
./scripts/start_postgres.sh

# 2. 后端
cd backend
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_demo      # 载入虚构租约 + 4 个演示航次
python3 manage.py test           # 16 个测试：引擎/不变性/API
python3 manage.py runserver

# 3. 前端（另开终端）
cd frontend
npm install
npm run dev                      # http://localhost:5173（/api 代理到 8000）
```

数据库连接用环境变量覆盖：`PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD`。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/voyages/` `/api/voyages/{id}/` | 航次列表 / 详情（含事件、停工、条款、结算） |
| POST | `/api/voyages/{id}/calculate/` | 试算（不落库），返回完整可追溯报告 |
| POST | `/api/voyages/{id}/settle/` | 以当前试算生成**新版本**结算草稿 |
| GET/POST/PATCH | `/api/events/` `/api/stoppages/` | 事实维护（含证据状态） |
| GET | `/api/settlements/?voyage=` | 结算版本列表 |
| POST | `/api/settlements/{id}/finalize/` | 定稿（含待核对事实 → 400） |
| DELETE | `/api/settlements/{id}/` | 仅草稿可删；已定稿 → 400 |
| GET | `/api/charter-parties/` | 租约与条款 |

### 报告结构（节选）

```jsonc
{
  "status": "OK | PROVISIONAL | BLOCKED",
  "commencement": { "at": "...", "turntime_clause": "FIC-02" },
  "time_summary": {
    "natural_hours": "96.0000",      // 自然时间
    "working_hours": "90.0000",      // 实际作业时间
    "laytime_used_hours": "72.0000", // 允许计入时间
    "demurrage_hours": "20.0000"
  },
  "segments": [ { "kind": "COUNTING|EXCLUDED|DEMURRAGE", "start": "...", "end": "..." } ],
  "exclusions_applied": [ { "reasons": ["恶劣天气"], "clause_codes": ["FIC-03"], "stoppage_ids": [3] } ],
  "charges": [ {
      "type": "DEMURRAGE", "amount": "10000.00",
      "period": { "from": "...", "to": "..." },
      "trace": { "rate_clause": "FIC-07", "allowed_clause": "FIC-01",
                 "once_on_demurrage_clause": "FIC-09",
                 "formula": "20.0000小时 ÷ 24 × 12000/天" }
  } ],
  "unverified_inputs": [ ... ]
}
```

## 目录结构

```
backend/
  config/            # Django 配置（PostgreSQL）
  laytime/
    models.py        # 事实、条款、结算（含不可变约束）
    engine.py        # 核算引擎（Decimal、区间并集、时间轴推进）
    views.py         # DRF API（试算/结算/定稿）
    tests.py         # 16 个测试
    management/commands/seed_demo.py
frontend/
  src/components/    # 时间轴、条款、核算报告、结算版本面板
scripts/
  start_postgres.sh
```
