# RevOS 部署与监控手册

## 1. 环境变量（生产必填）

| 变量 | 说明 | 生产要求 |
|---|---|---|
| `ENVIRONMENT` | production | 必须为 production（触发默认密钥门禁） |
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+psycopg://…` |
| `API_KEYS` | 服务端 API Key | 禁止默认值，可多个逗号分隔 |
| `API_KEY_ORG_MAP` | API Key → organization_id 映射 | **必填**（JSON） |
| `AUTH_SECRET` | JWT 密钥 | 禁止默认值 |
| `WEBHOOK_SECRET` | Webhook 签名密钥 | 禁止默认值 |
| `REVOS_WECOM_CORPID/SECRET/AGENT_ID` | 企微凭证 | 接入真实企微时必填 |
| `REVOS_TEXT_PROVIDER_URL/API_KEY/MODEL` | LLM 供应商 | 接入真实 AI 时必填 |
| `REVOS_WX_APPID/SECRET` | 小程序凭证 | 接入真实小程序时必填 |

生产启动门禁：`ENVIRONMENT=production` 时若发现默认开发密钥或缺少 API_KEY_ORG_MAP，应用**拒绝启动**。

## 2. 部署步骤

```powershell
# 1) 后端
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 2

# 2) 前端（构建产物由 nginx 托管，frontend/nginx.conf）
cd frontend
pnpm install
pnpm build

# 3) 一键启动（开发）
.\启动系统.ps1
```

Docker：仓库根 `docker-compose.yml` + `backend/Dockerfile` + `frontend/Dockerfile` 可编排（需自行补充镜像仓库/密钥注入）。

## 3. 密钥管理

- 所有密钥只经环境变量注入，**不进入代码、日志、数据库明文字段和前端**。
- `customer_identities.encrypted_value`：生产建议用 Fernet/云 KMS 加密后写入（当前为源系统值直存，见迁移说明 §4）。
- Webhook 签名使用 `WEBHOOK_SECRET`（HMAC-SHA256），订阅级 secret 优先。

## 4. 监控指标（规格 14.3）

| 类别 | 指标 |
|---|---|
| 机会 | 识别数量与耗时、去重/抑制率、过期数 |
| AI 调用 | 成功率、延迟、成本、模板兜底率 |
| 审核 | 自动检查拦截率、人工通过率与耗时、待审积压 |
| 企微 | 待员工确认积压、发送成功/未知/失败率、external_userid 覆盖率 |
| 小程序 | ticket 打开率、事件回流率 |
| 漏斗 | 回复→预约→到店→支付转化、DNC/投诉计数 |
| 归因 | 计算失败/重算次数、数据质量等级 |

现有基础：`GET /api/v1/health`；事件流 `GET /api/v1/events`；投递日志 `GET /api/v1/webhooks/deliveries`；策略护栏 `GET /api/v1/strategy-performance/guardrails`。生产可加 Prometheus 导出（后置项）。

## 5. 故障处理

| 场景 | 处理 |
|---|---|
| 企微 token 失效 | HttpWeComProvider 自动刷新重试一次（40014/42001/40001） |
| 企微频控/无关系 | 不盲目重试（45009/45010/84061/84062），标记失败并人工处理 |
| 发送状态未知 | `query_unknown_status` 先查询，禁止直接重复发送 |
| 内容审核冲突 | 409 CONTENT_CHANGED：重新审核最新版本 |
| 策略效果下降 | `evaluate_guardrails` 输出建议 → 人工批准回滚（`POST /strategy-versions/{id}/rollback`） |
| 每日任务失败 | 调度日志 `clinicos.scheduler`，可手动 `POST /api/v1/customers/recompute-all` 补偿 |

## 6. 回滚策略

- 数据库：`alembic downgrade a715f4a894bb`（见《RevOS迁移与回滚说明》）。
- 代码：按 Git 基线回退（需负责人先建立 Git 仓库）。
- 策略：`strategy_versions` 单版本回滚不影响既有执行数据。
