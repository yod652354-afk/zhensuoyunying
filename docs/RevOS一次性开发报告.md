# RevOS 一次性完整开发报告

> 依据《RevOS-DeepSeek工程开发包-V2.0》执行：ClinicOS → RevOS 兼容式升级，一次性交付全部核心能力。
> 交付口径：本报告中的内部检查点不代表分期交付；除「等待外部凭证」的真实联调项外，无 TODO/占位。

---

## 1. 现有实现事实（开发前审计）

- 后端：FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic（初始迁移 `a715f4a894bb`），SQLite/PostgreSQL 双兼容。
- 前端：Vue 3 + Element Plus + Pinia + ECharts（13 个页面）。
- 基线测试：**43 项通过**（审计报告声明），本次开发前复跑发现 `test_a17` 因测试库状态残留假失败，已在 conftest 修复测试基座（每次会话重建测试库），恢复为确定性 43 通过。
- 既有资产：Patient/Visit/Appointment/Order/Payment/Task/Touch/Campaign/Experiment/Attribution/Event/ContentReview 等 30+ 实体；Read/Write/Webhook/Analytics/Import API；Recovery/Retention/Attribution/Dashboard 等服务。
- P0 风险确认：无 Git 基线（本机未安装 git，改用源码 zip 基线 `_extracted/../.tmp/ClinicOS-Baseline-*.zip`，185 个源文件）；租户隔离不足（Read API 用客户端参数过滤）；默认开发密钥。

## 2. 本任务目标

在既有代码库内原地完成 RevOS 升级：客户经营档案 → 生命周期/三种钱状态机 → Opportunity → Decision → ExecutionPlan → 自动合规 + 人工审核 → 企微员工确认执行 → 小程序承接 → Outcome → 增量归因 → 策略版本与学习。同时修复租户安全基线，保留全部旧功能/数据/API。

## 3. 复用 / 扩展 / 新增 / 废弃清单

| 类型 | 内容 |
|---|---|
| 复用 | Patient/Visit/Appointment/TreatmentPlan/Order/Payment/Package/Task/Touch/Campaign/Experiment/Event/ContentReview 全部保留；Recovery 规则评分复用为 past-money Detector；Retention 超期/No-show 复用为 current-money Detector；resolve_assignee/模板库/事件总线原样复用 |
| 扩展 | Task（15 列：opportunity_id/execution_plan_id/content_draft_id/send_status/confirmed_by/…）；Touch（12 列）；Attribution（7 列）；Event（schema_version/correlation_id/causation_id）；WebhookDelivery（organization_id）；MessageTemplate 查询加 org 过滤 |
| 新增 | 领域模型 17 表 + 服务 16 模块 + API 49 端点 + 前端 8 页面 + 测试 53 项 |
| 废弃 | 无（未删除任何既有功能）；Recovery/Retention 不再直接各自创建任务（改由 Opportunity/仲裁统一驱动，旧任务接口保留兼容） |

## 4. 修改文件（按目录）

### 后端核心
- `backend/app/models/revos.py`（新增 17 个领域模型）
- `backend/app/models/{task,marketing,experiment,event}.py`（扩展列）
- `backend/app/models/__init__.py`（注册）
- `backend/app/core/{tenant,ids,enums,config}.py`（租户上下文、ID 前缀、RevOS 枚举、配置）
- `backend/alembic/versions/b2c9d4e1f0a3_revos_upgrade.py`（**新增 migration，未修改初始 migration**）
- `backend/app/services/revos/`（16 模块：customer_state / opportunity / arbitration / psychology / decision / execution_plan / content_provider / compliance_check / review / wecom / mp / outcome / attribution / strategy / events / common）
- `backend/app/api/v1/revos.py`（49 端点）
- `backend/app/api/v1/{read,write,analytics,operations,webhooks,imports,templates,auth,uploads}.py`（租户强制）
- `backend/app/events/{bus,dispatcher}.py`（事件规范扩展）
- `backend/app/services/{dashboard,reports,retention,quality,attribution,recovery,task_engine,templates,scheduler}.py`（org 过滤 / 每日补偿）
- `backend/app/main.py`（生产密钥门禁 + RevOS 路由）
- `backend/tests/`（conftest 修复 + 10 个新测试文件）

### 前端
- `frontend/src/views/revos/`（8 页面：三种钱驾驶舱 / 机会池 / 机会详情 / 审核中心 / 员工执行 / 客户档案 / 实验归因 / 策略中心）
- `frontend/src/router/index.js`（新增 RevOS 路由，保留旧路由）
- `frontend/src/App.vue`、`frontend/src/views/LoginView.vue`（品牌 RevOS）
- `frontend/src/api/client.js`（API Key 仍为兼容默认值，提示生产必换）

### 根目录
- `.env.example`（新增 REVOS_* 配置模板）、`启动系统.ps1`（启动前自动迁移）、`README.md`（升级说明）

## 5. 新增 Migration

- `b2c9d4e1f0a3_revos_upgrade`：17 张新表（customers/customer_identities/customer_state_history/opportunities/context_snapshots/decisions/execution_plans/content_drafts/content_review_records/actions/outcomes/interaction_sessions/mp_events/workflow_definitions/workflow_instances/strategy_versions/strategy_performance）+ 既有表扩展列。
- 验证：SQLite 全循环 `upgrade → downgrade(a715f4a894bb) → re-upgrade` 通过（53 → 36 → 53 表）；PostgreSQL 类型全部使用 sa.String/Numeric/JSON/DateTime/Boolean/Integer，兼容。
- 回滚：`alembic downgrade a715f4a894bb`（先删 RevOS 新增索引再删列/表，batch 模式支持 SQLite）。

## 6. 新增/变更接口（49 端点）

- **客户档案**：GET /customers（列表/筛选）、GET /customers/{id}、GET /customers/{id}/revenue-profile、GET /customer-identities、GET /customer-states、GET /state-transitions、POST /customers/recompute-all
- **Opportunity**：POST /opportunities/detect/{scenario}、GET /opportunities、GET /opportunities/{id}、PATCH …/suppress、POST …/qualify、POST …/assign-experiment、POST …/arbitrate、POST …/decide、POST …/execution-plan、POST …/generate-content、GET …/outcomes
- **决策/方案**：GET /decisions、GET /execution-plans、GET /execution-plans/{id}、POST /execution-plans/{id}/review
- **内容**：GET /content-drafts、GET /content-drafts/{id}、GET …/versions、POST …/machine-check、POST …/review、POST …/request-change、POST …/regenerate、POST …/create-send-task
- **企微执行**：GET /send-tasks、POST /send-tasks/{id}/prepare-wecom、…/confirm-sent、…/mark-failed、…/record-response、GET /touches/{id}
- **结果/归因**：POST /outcomes/sync、POST /experiments/{id}/calculate、GET /experiments/{id}/metrics、GET /attributions/{opp_id}/trace
- **小程序**：POST /mp/sessions/issue、GET /mp/sessions/{ticket}/offer、POST /mp/events、POST /mp/login
- **策略**：GET/POST /strategy-versions、POST …/transition、POST …/rollback、GET /strategy-performance、GET /strategy-performance/guardrails
- **驾驶舱**：GET /analytics/revos/cockpit
- 全部既有接口保持兼容（响应包络/分页/事件流不变），并新增服务端租户强制。

## 7. 事件变化

- Event 表新增 `schema_version / correlation_id / causation_id`；`emit()` 支持透传。
- 新增事件类型：customer.state_changed、opportunity.detected/qualified/suppressed/won/lost、decision.created、execution_plan.created/reviewed、action.executed、content.generated/machine_checked/review_approved/review_rejected/review_changes_requested、send_task.created、touch.waiting_confirmation/sent/failed/unknown/delivered、customer.responded、mini_program.opened、outcome.recorded、attribution.calculated、strategy.deployed/rolled_back/retired。
- WebhookDelivery 新增 organization_id（历史数据回填），投递日志按租户隔离。

## 8. 测试命令与结果

```powershell
cd D:\个人文件\下载\诊所决策系统\backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

最终结果：**96 passed**（原 43 项全部保留通过 + 新增 53 项）：
- 租户安全（跨租户 list/detail/write 拒绝、员工 store 强制、生产默认密钥拒绝、匿名拒绝）
- 状态机（迁移历史、三种钱 reason_codes、手机号变更稳定 ID、每日补偿）
- Opportunity（识别、评分、去重、DNC 排除、状态流转、过期、实验分组、对照组 403）
- 仲裁（DNC/投诉/频控门禁、对照组保护、单主计划、心理策略证据）
- ExecutionPlan（全链路：决策→方案→内容→机器检查→人工审核→发送任务；未审核禁止创建任务；篡改 409）
- 企微契约（模拟器、发送幂等、DNC 阻断、不确定状态先查询）
- 小程序（ticket 篡改/过期/撤销拒绝、事件幂等、支付伪造拒绝、内容不含内部标识）
- Outcome/归因（结果状态迁移、客户端支付拒绝、增量数学、小样本方向性、证据链）
- 策略（版本递增、流转白名单、护栏人工批准、回滚、影子运行）
- 事件（schema 字段、目录齐全、回放幂等）

## 9. 安全检查

- ✅ 跨租户 list/detail/write/import/analytics/files/webhooks 全部服务端强制（403/404）
- ✅ 员工 JWT 强制 store scope；boss/admin 全门店
- ✅ 生产模式启动拒绝默认 API Key/JWT Secret/Webhook Secret（且要求 API_KEY_ORG_MAP）
- ✅ DNC/投诉/未授权/频控在「实际发送前」再次检查（`final_pre_send_check`）
- ✅ 未审核内容无法创建发送任务；审核后内容篡改返回 409
- ✅ 对照组不生成内容/任务/触达（API 层 + 发送层双门禁）
- ✅ 小程序 ticket 高熵、短期、可撤销、跨客户防护；明文 token 不落库
- ✅ 支付结果不接受客户端伪造（客户端上报 payment_success 拒绝）
- ✅ 不确定发送状态先查询、禁止盲目重复发送；发送幂等（task_id + content_hash）
- ✅ 身份值加密列 + 匹配哈希分离；日志/响应脱敏辅助（mask_mobile/mask_identity/redact_payload）
- ✅ 密钥来自环境变量，不进入代码/日志/前端
- ⚠️ 既有患者 API 按诊所SaaS合同仍返回原始 mobile（合同兼容）；RevOS 客户 API 一律脱敏

## 10. 兼容性说明

- 旧表旧数据不删除；Task/Touch/Attribution/Event 新增列全部 nullable，旧数据可读。
- 既有 30 类 Read API、Write API、Webhook、Import、Analytics 接口与响应结构不变。
- Recovery Pool / Retention 列表接口保留（内部数据源已可映射为 Opportunity 查询）。
- Patient API 内部可调用 Customer 领域服务（ensure_customer 按需建档）。
- 品牌：UI 与 README 切换为 RevOS；未做全局机械字符串替换（规格 §10.1 第一阶段口径）。

## 11. 未完成项（唯一允许等待项：真实外部凭证）

- **真实企微联调**：Provider（HttpWeComProvider）、模拟器（SimulatedWeComProvider）、契约测试、员工确认任务流已完整实现；`REVOS_WECOM_MODE=http` + corpid/secret 后即可联调真实企微 token/成员确认接口。
- **真实 LLM/图片供应商联调**：HttpJsonTextProvider/HttpJsonImageProvider 已实现（超时/重试/成本/JSON Schema 校验/模板兜底），配置 `REVOS_TEXT_PROVIDER=http` + URL/Key/Model 即可接入。
- **真实小程序 code2session**：wx_login_session 已实现，配置 `REVOS_WX_APPID/SECRET` 后启用；无凭证时返回模拟 openid。
- **真实门店验收**：首场景「高价值沉睡客户召回」的代码/测试/演示数据已就绪，需真实门店 + 诊所SaaS数据源 + 企微环境后按《04-测试与验收门禁》执行（≥100 名合格客户、Treatment/Holdout、0 条 DNC 违规）。
- **生产队列**：调度/Webhook 重试仍为单进程模型（审计报告 P1），已记录为生产化事项（Outbox/持久队列在 Phase 4 规格中）。
- **Git 基线**：本机无 git，已用 zip 基线替代；负责人应初始化 Git 仓库并提交。

## 12. 禁止声明遵守情况

按《00-总开发指令》禁止声明：未宣称已实现自动运营/增量收入/AI 学习/生产可用/多租户安全（真实门店联调与 Treatment/Holdout 验证完成前）。本报告仅陈述代码能力与测试结果。

## 13. 下一步建议

1. 负责人初始化 Git 并把本报告列为评审入口；
2. 配置真实企微 corpid/secret（http 模式）→ 运行契约联调；
3. 接入真实诊所SaaS 数据源（OpenAPI/Webhook）→ 完成 A01-A30 差异矩阵验收；
4. 在真实门店执行首个场景验收（100 名客户、对照组、审核 100%、0 DNC 违规）；
5. 生产化：PostgreSQL、持久队列/Outbox、监控告警、备份恢复；
6. 按 Phase 3 用配置方式复制第二个工作流（复诊超期/疗程中断），验证 Core 抽象复用。
