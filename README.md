# RevOS — 大健康门店经营智能平台（ClinicOS 兼容升级）

> RevOS = ClinicOS 数据与工作流底座 + 三种钱经营模型 + Opportunity Engine + Decision/Workflow Engine + 人工审核的 AI Execution Engine + Outcome/Revenue Attribution + Action→Outcome 学习数据。
> 本仓库已按《RevOS-DeepSeek工程开发包-V2.0》完成**一次性完整开发**，并按《RevOS-修复与继续开发工程包》完成**一次性修复与继续开发**（对照组自然结果、统一每日运营链、浏览器无 API Key、事实-归因分层防广播、数据库唯一约束/外键、企微状态闭环、Outbox/持久 Job、Connector 自动接入、ORM 告警修复、前端代码分割）。
>
> 升级说明：详见 `docs/RevOS一次性开发报告.md`；修复闭环详见 `docs/RevOS修复与继续开发报告.md`；迁移/回滚见 `docs/RevOS迁移与回滚说明.md`；部署/监控见 `docs/RevOS部署与监控手册.md`。

> 原 ClinicOS 定位（兼容层）：对应《ClinicOS_诊所SaaS数据与API接口完整需求规格_V1.0》的**数据底座 + REST API + Webhook/Event + 运营后台**。不是 HIS/CRM，而是位于现有诊所系统之上的「经营决策与执行层」。

## RevOS 核心链路

```text
Customer → Customer Value State（生命周期 + 三种钱）
→ Opportunity（发现/去重/评分/仲裁/实验分组）
→ Decision（Next Best Action + 消费心理策略证据）
→ ExecutionPlan（目标/步骤/渠道/内容/停止条件）
→ 自动合规检查 → 人工审核（不可变版本 + 内容哈希）
→ 企微员工确认发送 → 小程序承接 → 预约/到店/支付回流
→ Outcome → 增量归因（Treatment/Holdout）→ 策略版本学习
```

## RevOS 新增页面（前端一级导航）

三种钱驾驶舱 · 经营机会池 · 今日执行（员工端）· 内容审核中心 · 客户经营档案 · 实验与增量归因 · 策略注册中心

## 三大引擎（产品主干，已升级为 Opportunity Detector/Workflow）

| 引擎 | 解决的问题 | 本仓库实现 |
|---|---|---|
| **Recovery**（过去的钱） | 沉睡/流失客户识别与增量回款 | Recovery Score 规则版、客户池、任务生成（`app/services/recovery.py`） |
| **Retention**（现在的钱） | 诊后复诊漏斗与超期预警 | 建议→预约→履约→复诊漏斗、今日应复诊/超期列表（`app/services/retention.py`） |
| **Growth**（未来的钱） | 活动/实验与增量营销 | Campaign + 受众 + 实验 A/B/Holdout 归因（`app/services/attribution.py`） |

## 技术栈

- **后端**：Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Pydantic v2（自动生成 **OpenAPI 3.1**）
- **数据库**：SQLite（本地零配置开发）⇄ PostgreSQL（生产，改 `.env` 的 `DATABASE_URL` 即可）
- **前端**：Vue 3 / Vite / Element Plus / Pinia / ECharts

## 目录结构

```
backend/
  app/
    main.py             # FastAPI 入口（lifespan 建表 + 种子数据）
    config.py           # .env 配置
    database.py         # 引擎/会话（SQLite/PostgreSQL）
    core/               # 稳定ID、枚举、统一错误、cursor分页、API Key 认证
    models/             # 23+ 实体（Patient/Visit/Appointment/Order/Payment/Package/Task/Event...）
    schemas/            # 写入模型 + 动态响应模型
    api/v1/             # Read(30端点) / Write(16端点) / Webhook / Analytics / Import
    events/             # 事件总线 + Webhook 投递器（签名/重试/投递日志/幂等）
    services/           # Recovery / Retention / Attribution / Dashboard / Quality
    seed.py             # 演示数据（1机构+1门店+3医生+40患者+活动+实验）
  tests/                # 验收测试（对照需求规格 A01-A30，24 项）
frontend/
  src/views/            # 驾驶舱/患者/Recovery池/今日任务/Retention漏斗/Growth/实验/质量/合规/Webhook
docs/技术架构说明.md    # 架构说明
```

## 快速启动

### 1. 后端（端口 8001）

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

- 启动时自动建表并写入演示数据（`SEED_DEMO_DATA=true`）
- API 文档：http://127.0.0.1:8001/docs （OpenAPI 3.1）
- 健康检查：http://127.0.0.1:8001/health

### 2. 前端（端口 5173）

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器打开 http://127.0.0.1:5173 （Vite 代理 `/api` → 后端 8001）

### 3. 验收测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

## 配置（.env）

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | `sqlite:///./clinicos.db`（开发）或 `postgresql+psycopg://user:pass@host:5432/clinicos`（生产/你的数据服务器） |
| `API_KEYS` | 逗号分隔的服务端 API Key（请求头 `X-API-Key`） |
| `WEBHOOK_SECRET` | Webhook HMAC-SHA256 签名密钥 |
| `WEBHOOK_DELIVERY_MODE` | `log`（开发，仅记日志）/ `http`（真实投递+指数退避重试） |
| `SEED_DEMO_DATA` | 是否写入演示数据 |

## 新增能力（对照项目计划书 V4.1 补全）

| 能力 | 入口 |
|---|---|
| 登录与角色权限（老板端/员工端，JWT） | `POST /auth/login`（boss/boss123、staff/staff123） |
| 话术模板库（Prescription：渠道×话术×版本） | 系统设置页 / `POST /message-templates` |
| Retention 自动任务引擎（超期/No-show/疗程中断→任务） | `POST /analytics/engine/retention-tasks` |
| Campaign 级增量归因（control vs treatment） | `GET /analytics/campaigns/{id}/metrics` |
| 实验显著性检验（z 检验 + 方向性信号标记） | 实验中心（conclusion: significant/marginal/directional） |
| 医生/员工维度过程漏斗（建议率<30% 自动 flag） | `GET /analytics/funnel-by-doctor` |
| 驾驶舱月度总结果（Recovery+Retention+Growth 汇总）+ 员工激励（按增量价值） | 经营驾驶舱 |
| 数据对账（每日核对，差异定位到 ID） | `GET /analytics/reconciliation` |
| Revenue Leakage Report（漏损节点/医生/项目分布） | `GET /analytics/revenue-leakage-report` |
| 营销内容合规（风险词扫描 → 人工审批 → 留痕） | 合规审计页 / `POST /compliance/scan` |
| 每周复盘（Action→Outcome 人工闭环） | `POST /reviews` / 经营报表页 |
| Webhook 持久化重试 worker（后台线程，指数退避） | 自动启动，`GET /webhooks/deliveries` 查看 |
| 每日自动任务调度（09:00 自动生成，可配置） | `.env` 的 `TASK_SCHEDULE_*`；`GET /events` 查看调度事件 |
| 任务分配：谁看诊谁负责 + 负载均衡 | 主诊员工优先 → 主诊医生 → 待办最少员工 |
| 执行反馈上传通道（文字 + 图片） | 员工完成任务时提交，`POST /api/v1/upload` |
| 老板审核任务（通过/退回重做/自动催办） | `PATCH /api/v1/tasks/{id}/review`，前端「待审核」Tab |

## 生产化

- **Alembic 迁移**：`cd backend && .venv\Scripts\python -m alembic upgrade head`（初始 `a715f4a894bb` + RevOS `b2c9d4e1f0a3`，共 53 表）
- **Docker 部署**：`docker compose up --build`（postgres + backend:8001 + frontend:8080）
- **CI**：`.github/workflows/ci.yml`（后端 pytest + 前端构建）
- **生产安全门禁**：`ENVIRONMENT=production` 时拒绝默认 API Key/JWT/Webhook 密钥并强制 `API_KEY_ORG_MAP`（否则拒绝启动）

## RevOS 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
# 142 passed（原 43 回归 + RevOS 59 项 + 修复验收 40 项）
# 覆盖：租户安全/状态机/机会/仲裁/方案审核/企微契约/小程序/归因/策略/事件/
#       对照组自然结果/调度统一链/归因防广播/数据库约束/企微回调/Outbox/Job/Connector/前端安全扫描
```

## 系统说明书

- **《ClinicOS 系统使用说明书》**：docs/系统使用说明书.md（登录/每个页面的操作/三大引擎闭环/FAQ/配置）
- **二期规划**：docs/项目规划书-企微触达与AI内容引擎.md（企微触达+小程序+AI 内容引擎）
- **企微技术研究**：docs/企业微信触达技术可行性研究报告.md
- **小程序对接契约**：docs/小程序对接需求文档.md（交小程序开发团队）

## 运营文档（docs/）

- 三套 SOP：`docs/sop/运营SOP-01-沉睡客户激活.md`、`SOP02-revisit-management.md`、`SOP03-campaign-execution.md`
- 数据字典：`docs/数据字典.md` ｜ 合规检查清单：`docs/合规检查清单.md` ｜ 试点包：`docs/试点入门包.md`

## 需求规格对应

- 数据实体：需求规格 §4（23+ 实体，P0 全部实现，P1 预留）
- Read API：§5.2（约 30 端点：列表/详情 + cursor 分页 + `created_since/updated_since` 增量 + `include_deleted`）
- Write API：§5.3（task/followup/appointment/tags/stage/campaign/audience/touch/experiment/attribution + `Idempotency-Key`）
- Webhook/Event：§6（标准事件包络、HMAC 签名、指数退避重试、投递日志、event_id 幂等、`/events/replay` 补偿）
- 数据质量：§8.2（完整性/一致性/时效性/授权四维评分）
- 增量归因：§9（Treatment−Holdout 增量 Lift、增量客户数、增量收入、ROI）
- 验收清单：§12（A01–A30 + 新增 B01–B14，共 **43 项自动化测试全部通过**）

## 重要边界（来自需求规格）

1. **增量收入口径**：所有对外价值一律用「增量」（Treatment − Holdout），不把自然回款算作系统功劳。
2. **数据最小化**：MVP 不采完整病历/诊断/处方；DNC/投诉/无效号码全局生效，不进营销队列。
3. **幂等与历史**：关键对象稳定唯一 ID、软删除、事件历史保留；Webhook 消费按 `event_id` 幂等。