# RevOS 一次性修复与继续开发报告

> 依据《RevOS-修复与继续开发工程包》执行：修复代码审核报告全部 P0/P1 问题并完成生产化关键能力。
> 决策引用：原V2.2开发规格《05-产品决策记录.md》D-016（共识记录机制）、D-017（修复决定）。
> 交付口径：一次性完成，不以"后续阶段"代替；除真实账号/凭证/第三方审批外无代码侧未完成项。

---

## 1. 审核问题逐条闭环表

| 问题 | 根因 | 修复文件 | 测试证据 |
|---|---|---|---|
| **P0-1 对照组自然结果被丢弃** | `sync_from_trusted_event` 对 control 机会 `continue`，对照组转化率恒为 0 | `app/services/revos/outcome.py`（重写 sync：所有组写 Outcome，control 标记 `is_organic` + `link_type=organic_control`）；`app/services/revos/attribution.py`（experiment_metrics 两组同口径、退款冲减净收入） | `test_revos_fix_control_group.py`（6 项：organic 记录、20%vs10% 增量 10pp、双 10% 增量 0、退款冲减、对照组禁生成内容） |
| **P0-2 每日调度绕过审核** | `run_daily_tasks` 直接调用旧 generate_recovery_tasks/run_retention_engine | `app/services/scheduler.py`（重写为统一运营链：状态重算→Detectors→机会去重/过期→仲裁→Decision→ExecutionPlan→内容+机器检查→待审核；按组织/门店循环、错误隔离）；`app/api/v1/{operations,analytics}.py`（旧引擎端点转为兼容入口，不再创建旧 Task） | `test_revos_fix_scheduler.py`（4 项：不创建旧 Task、每组织处理、单租户失败隔离、兼容端点转机会） |
| **P1-1 前端内置默认 API Key** | client.js 无 JWT 时回退 `dev-key-change-me` | `frontend/src/api/client.js`（仅 JWT）；`router/index.js`（未登录跳登录）；`TodayTasksView/DataQualityView`（上传/导入仅 JWT）；删除陈旧 dist | `test_frontend_security_scan.py`（4 项：源码/dist 无密钥、仅 JWT、路由守卫）；dist 实扫无密钥 |
| **P1-2 迁移缺数据库约束** | 仅普通索引，无唯一约束/外键 | `alembic/versions/b3c9d4e1f0a4_revos_fix.py`（11 类唯一约束含部分唯一索引 + 6 组外键）；模型 `__table_args__`（create_all 与迁移一致） | `test_revos_fix_db_constraints.py`（5 项：索引存在、活动机会唯一、BusinessFact 源唯一、同版本 Plan 拒绝、迁移循环） |
| **P1-3 企微真实状态查询未实现** | `query_status` 固定返回 UNKNOWN | `app/services/revos/wecom.py`（HttpWeComProvider.query_status 实现真实结果查询映射；send 语义修正为 waiting_member_confirmation；回调验签/幂等/状态更新；UNKNOWN 禁止自动重发） | `test_revos_fix_wecom_callback.py`（7 项：状态语义、验签、幂等、未知拒绝、UNKNOWN 不重发、无关系永久失败、端点 403） |
| **P1-4 一笔支付广播给全部机会** | 按 patient_id 命中所有活动机会 | 新增 `app/models/business.py`（BusinessFact/OpportunityOutcomeLink，同事实一个 primary 部分唯一索引）；`app/services/revos/fact_matching.py`（窗口/主Plan/Touch/场景匹配，无证据进人工队列）；`outcome.py` 重构 | `test_revos_fix_attribution_dedup.py`（4 项：一事实一 primary、窗口外不匹配、无证据人工队列、退款关联原支付） |
| 其他-ORM 告警 | 模型重复赋值 `created_at = CommonMixin.created_at` 触发 Unmanaged access 告警；main.py 全局隐藏 | 全部模型类声明改为继承 `(CommonMixin, Base)` / `(TimestampMixin, Base)`，删除冗余显式字段；`app/models/base.py` CommonMixin 显式转发三列；删除 main.py 过滤 | import 全程无告警（`warnings.simplefilter("error")` 验证）；alembic 命令无该类告警 |
| 其他-单进程调度 | scheduler/worker 仅进程内 | 新增 `app/models/outbox.py`（OutboxMessage/Job）+ `app/services/revos/{outbox,jobs}.py`（事务性 Outbox、租约领取、心跳、指数退避、死信、人工重放、多实例唯一）；main.py 启动 worker | `test_revos_fix_outbox_jobs.py`（6 项：回滚不发布、提交发布、唯一领取、租约接管、死信+重放、重启持久） |
| 其他-无自动数据接入 | 缺 Connector | 新增 `app/models/connector.py` + `app/services/revos/connector.py`（全量/增量/游标/补偿/Webhook/对账/模拟 SaaS）+ API | `test_revos_fix_connector.py`（5 项：分页游标、全量增量幂等、租户游标隔离、Webhook 回流去重、对账） |
| 其他-无 Git 仓库 | 本机未安装 git | 已通过 winget 安装 Git 2.55 并初始化仓库：基线提交 `a0c0e41`（206 文件，敏感/依赖目录全部 .gitignore 排除），后续提交 `af57870` | 报告 §8；`git log` 可查 |

## 2. R-01 ~ R-11 完成情况

| 项 | 状态 | 关键实现 |
|---|---|---|
| R-01 对照组自然结果 | ✅ | Outcome.is_organic + organic_control link；experiment_metrics 同窗口同口径；退款冲减 |
| R-02 统一每日运营链 | ✅ | 调度器重写；旧引擎 API 兼容转统一流程；每组织/门店循环 + 错误隔离 |
| R-03 移除浏览器 API Key | ✅ | 前端仅 JWT；静态扫描测试；dist 无密钥 |
| R-04 事实与归因分层 | ✅ | BusinessFact → OpportunityOutcomeLink → Attribution；一事实一 primary；人工归因队列 |
| R-05 数据库约束 | ✅ | 11 类唯一约束（含部分唯一索引，枚举 name 大小写适配）+ 6 组外键；SQLite/PostgreSQL 兼容 |
| R-06 企微状态闭环 | ✅ | add_msg_template → waiting_member_confirmation；回调验签/幂等/状态更新；真实结果查询；UNKNOWN 不重发 |
| R-07 Outbox/持久 Job | ✅ | 事务性 Outbox + 租约 Job（唯一领取/心跳/退避/死信/重放/多实例/重启恢复） |
| R-08 修复 ORM 告警 | ✅ | mixin 继承化 + CommonMixin 转发；删除全局隐藏；无告警 |
| R-09 通用 Connector | ✅ | 配置/全量/增量/游标/补偿/Webhook/对账/模拟 SaaS + 契约测试 + API |
| R-10 前端继续开发 | ✅ | 认证修复；自动运营运行中心/待人工归因/Connector 页面；角色路由；生产构建代码分割 |
| R-11 报告与版本控制 | ✅ | 本报告（142 测试、P0/P1 闭环表）；**Git 仓库已初始化**（基线 `a0c0e41`）；引用 V2.2 D-017 |

## 3. 最终命令结果

```powershell
# 后端全部测试（分模块运行，142 项全部通过）
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
#   24+14+5+7+5+6+6+4+6+7+7+6+4+6+4+4+5+7+6+5+4 = 142 passed

# 迁移循环
.\.venv\Scripts\python.exe -m alembic upgrade head        # 61 表
.\.venv\Scripts\python.exe -m alembic downgrade b2c9d4e1f0a3  # 53 表
.\.venv\Scripts\python.exe -m alembic upgrade head        # 61 表
#   部分唯一索引 uq_opportunities_active_scenario 存在

# 前端生产构建
pnpm --dir frontend run build
#   ✓ built（vue-vendor/element-plus/echarts 按供应商代码分割；dist 无 dev-key-change-me/clinicos_api_key）
```

## 4. 新增 Migration

- `b3c9d4e1f0a4_revos_fix`（down_revision=b2c9d4e1f0a3）：business_facts / opportunity_outcome_links / outbox_messages / jobs / connector_configs / connector_runs / sync_checkpoints / reconciliation_diffs 8 张新表；outcomes（fact_id/is_organic）、actions（idempotency_key）、visits/orders/payments/refunds（source_id）扩展列；11 类唯一约束 + 6 组外键；历史重复数据清理（dedupe）；upgrade/downgrade 均可执行。
- `b4c9d4e1f0a5_revos_mixin_align`（down_revision=b3c9d4e1f0a4）：R-08 模型继承化后，为既有表补齐 store_id/source_system/created_by_type/created_by_id/deleted_at 缺失列（batch 模式幂等补列），保证 create_all 库与迁移库结构一致；upgrade→downgrade→upgrade 循环验证通过（61→61→61 表）。

## 5. 新增/变更接口

- POST /wecom/callback（回调验签+幂等状态更新）
- GET/POST /jobs、POST /jobs/{id}/requeue、POST /outbox/poll
- GET/POST /connectors、POST /connectors/{id}/sync|webhook、GET /connectors/{id}/runs
- GET /reconciliation/diffs、GET /attribution/manual-review-queue
- 旧引擎端点（/analytics/engine/retention-tasks、/analytics/recovery-pool/tasks）语义改为"转统一机会流程"

## 6. 事件变化

- 新增 `outcome.recorded` 携带 `is_organic`；`touch.{status}` 由回调驱动（含 callback 标记）；
- Outbox 发布的事件带 `source_system=revos_outbox`。

## 7. 未完成项

**无代码侧未完成项。** 外部依赖仅限：
- 真实企微 corpid/secret（HttpWeComProvider 已就绪，`REVOS_WECOM_MODE=http` 联调）；
- 真实 LLM/图片供应商凭证（HttpJsonProvider 已就绪）；
- 真实小程序 appid/secret（wx_login 已就绪）；
- 真实诊所 SaaS 环境（Connector 契约测试/模拟器已完成）；
- 真实门店验收（≥100 名客户、Treatment/Holdout、0 DNC 违规）。

## 8. Git 基线（R-11）

- 仓库：`D:\个人文件\下载\诊所决策系统`（Git 2.55 经 winget 用户级安装）
- 基线提交：`a0c0e41`（206 文件；`.env`/`*.db`/`.venv`/`node_modules`/`uploads`/`.tmp`/`dist` 全部忽略）
- 后续提交：`af57870`（移除沙箱临时配置）
- 后续开发按 R-11 要求逐修复点独立 commit。

## 8. 状态声明（00 总指令禁止声明）

按禁止声明：未完成真实企微联调、真实门店数据和 Treatment/Holdout 验证前，不宣称已实现自动运营/增量收入/AI 学习/生产可用/多租户安全（完整）。本报告仅陈述代码能力、模拟/契约测试与真实待联调项的明确区分。
