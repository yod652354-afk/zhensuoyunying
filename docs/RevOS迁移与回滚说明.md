# RevOS 数据库迁移与回滚说明

## 1. 迁移内容

| 项 | 值 |
|---|---|
| 迁移文件 | `backend/alembic/versions/b2c9d4e1f0a3_revos_upgrade.py` |
| 前置 revision | `a715f4a894bb`（初始 schema，**未修改**） |
| 目标 revision | `b2c9d4e1f0a3` |
| 新增表 | customers / customer_identities / customer_state_history / opportunities / context_snapshots / decisions / execution_plans / content_drafts / content_review_records / actions / outcomes / interaction_sessions / mp_events / workflow_definitions / workflow_instances / strategy_versions / strategy_performance（17 张） |
| 扩展表 | tasks（15 列）、touches（12 列）、attributions（7 列）、events（3 列）、webhook_deliveries（1 列，历史回填） |
| 兼容性 | 扩展列全部 nullable；旧表旧数据不删除；SQLite / PostgreSQL 均可执行 |

## 2. 升级命令

```powershell
cd D:\个人文件\下载\诊所决策系统\backend
# 预览将执行的 SQL（离线模式）
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
# 执行升级
.\.venv\Scripts\python.exe -m alembic upgrade head
# 查看当前版本
.\.venv\Scripts\python.exe -m alembic current
```

一键启动脚本（`启动系统.ps1`）会在启动后端前自动执行 `alembic upgrade head`。

## 3. 回滚命令

```powershell
# 回滚 RevOS 迁移（恢复初始 schema）
.\.venv\Scripts\python.exe -m alembic downgrade a715f4a894bb
# 或仅回退一个版本
.\.venv\Scripts\python.exe -m alembic downgrade -1
```

回滚内容：删除 17 张新表；删除 tasks/touches/attributions/events/webhook_deliveries 上的 RevOS 新增列与索引。**旧数据不受影响**（只移除新增结构）。SQLite 下删除带索引列使用 batch 模式（copy-and-move），已实测 upgrade → downgrade → re-upgrade 循环通过。

## 4. 数据迁移注意事项

- 手机号等身份：`customer_identities.encrypted_value` 为加密存储列（当前为源系统值直存，生产建议接入 Fernet/云 KMS 后加密写入）；`value_hash` 为 HMAC-SHA256 匹配哈希，二者分离。
- `customers` 为经营聚合视图：由 `ensure_all_customers` / 每日调度自动从 Patient 建档，无需手工迁移。
- `webhook_deliveries.organization_id`：迁移自动按 event_id 关联 events 回填历史投递记录。
- 学习快照（context_snapshots/opportunities.context_snapshot）只保存脱敏特征，不复制完整病历。

## 5. 备份与恢复建议

```powershell
# SQLite：复制库文件前先停服
Copy-Item backend\clinicos.db "clinicos_backup_$(Get-Date -Format yyyyMMddHHmm).db"
# PostgreSQL：pg_dump
pg_dump -h host -U user clinicos > clinicos_backup.sql
```

升级前必须：备份数据库 → 运行 43+53 回归测试 → 灰度环境验证迁移 → 生产执行。

## 6. 风险说明

- 迁移在 SQLite 下删除列依赖 batch 模式（已内置）；PostgreSQL 原生 ALTER 直接执行。
- `alembic downgrade` 后如需重新升级，`opportunities` 等表为全新状态，重复检测受去重约束保护，不会重复创建活动机会。
- 若迁移中途失败：SQLite 非事务 DDL，建议恢复备份重试；PostgreSQL 自动回滚事务。
