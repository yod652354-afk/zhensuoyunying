# ClinicOS 源码审计与 RevOS 升级启动报告

审计目录：`D:\个人文件\下载\诊所决策系统`  
审计日期：2026-08-29  
审计方式：只读源码检查、自动化测试执行、需求规格对照

## 1. 执行结论

该目录包含可运行的 ClinicOS 一期源码，不是仅有文档的原型。现有代码适合原地演进为 RevOS，不建议另建平行后端。

基线测试结果：

```text
43 passed, 1 warning in 7.22s
```

README 声明的43项自动化测试全部通过已经得到验证。

当前最准确的工程状态：

- 数据底座、REST API、事件、Webhook、任务、实验和基础归因已存在；
- Recovery、Retention 已有规则实现，但仍是各自独立 service；
- Task 是统一执行载体，但缺少 Opportunity、Decision、ExecutionPlan 和 Outcome；
- 当前身份、租户隔离和生产队列不满足规模化商用要求；
- 可以开始 RevOS Core 升级，但必须先建立版本控制和修复租户安全基线。

## 2. 已验证资产

### 后端

- FastAPI；
- SQLAlchemy 2；
- Pydantic v2；
- SQLite/PostgreSQL配置；
- Alembic初始迁移；
- 30类Read API注册；
- Write API；
- Webhook/Event；
- 幂等记录；
- Recovery规则评分；
- Retention漏斗与任务；
- Campaign/Experiment/Attribution；
- 登录与角色；
- 合规扫描；
- 任务反馈和审核；
- 数据质量、对账和报表；
- 调度与Webhook重试。

### 前端

- Vue 3；
- Element Plus；
- Pinia；
- ECharts；
- 驾驶舱、患者、Recovery、任务、Retention、Growth、实验、数据质量、合规、设置和报表页面。

### 测试

- A类需求规格验收测试；
- B类扩展能力测试；
- C类任务闭环测试；
- 共43项全部通过。

## 3. 与 RevOS 目标的差距

### 缺少统一 Opportunity

Recovery和Retention直接查询患者并创建Task。当前没有统一表达以下信息的领域对象：

- 三种钱类型；
- 具体机会场景；
- 状态和有效期；
- 价值、概率和成本；
- 判断证据；
- Decision版本；
- Workflow版本；
- 实验分组；
- 最终Outcome和归因。

### 缺少 ExecutionPlan

Task当前包含reason、expected_value、suggested_channel和模板，但无法表达完整执行方案：

- 心理策略及证据；
- 候选方案；
- 多步骤工作流；
- 内容及图片版本；
- 停止条件；
- 自动检查；
- 人工审核版本；
- 实际执行与建议的偏差。

### 客户状态只有当前值

Patient包含customer_status和customer_stage，但缺少不可变状态历史、三种钱主状态、价值快照和迁移原因。

### 身份模型过于简单

Patient直接保存mobile、wechat和enterprise_wechat_id。缺少有作用域、可变、可验证的CustomerIdentity，无法稳健处理手机号变更、多个企微主体和小程序身份。

### 学习数据不完整

现有Task、Touch、Event和Attribution提供了基础，但缺少Context、Decision、Strategy、Prompt、模型、人工修改和版本发布的完整快照。

## 4. 必须优先修复的工程风险

### P0：没有Git仓库

源码目录中不存在`.git`。在大规模升级前必须建立版本控制基线，确保：

- 现状可恢复；
- 每阶段可审查；
- 数据库迁移和代码可以对应；
- DeepSeek产生的改动可以逐批评审；
- 出现回归可以回滚。

初始化Git属于状态变更，应由项目负责人明确执行或授权。

### P0：租户隔离未在服务端强制

Read API把organization_id/store_id作为可选客户端过滤条件，而不是从当前登录用户强制注入。详情接口按实体ID直接读取，没有组织过滤。

Write API在缺少组织上下文时可能从患者、门店或数据库第一个组织推断organization_id。

这意味着当前“多租户”主要是数据字段设计，不是安全隔离。真实多门店部署前必须：

- 所有请求从认证上下文获得organization_id；
- 普通员工强制store_id；
- 查询、详情、写入、导入、分析、Webhook和文件均服务端过滤；
- 禁止客户端越权指定其他组织；
- 增加跨租户安全测试。

### P0：默认开发密钥

配置包含开发默认API Key、Webhook Secret和JWT Secret。生产启动必须拒绝默认密钥，并接入安全配置管理。

### P1：关键后台任务仍为单进程模型

调度和Webhook重试适合演示和单实例，不适合作为规模化关键执行基础。RevOS执行引擎需要持久队列、Outbox、死信、幂等和可见重放。

### P1：迁移只有单个初始基线

后续RevOS升级必须使用小步Alembic迁移，不得修改已使用的初始迁移文件。

### P1：前端依赖目录在项目目录内

`frontend/node_modules`已存在，体积较大。建立Git时必须确认被`.gitignore`排除，不得提交。

## 5. 现有代码应如何复用

| 现有模块 | RevOS处理 |
|---|---|
| Patient | 继续作为诊所行业客户事实映射，新增经营状态聚合层 |
| Recovery | 改为Past Money Opportunity Detector |
| Retention | 改为Current Money Opportunity Detector |
| Campaign/Growth | 保留，未来增加Future Money Detector |
| Task | 继续作为员工任务，关联Opportunity/ExecutionPlan/Action |
| Touch | 扩展为实际渠道动作和回执 |
| ContentReview | 扩展为ExecutionPlan人工门控 |
| Experiment | 继续承担Treatment/Holdout |
| Attribution | 扩展归因版本、窗口和证据链 |
| Event | 扩展correlation_id、causation_id和schema_version |
| Dashboard | 逐步改为基于Opportunity和Outcome |

## 6. 第一批工程文件建议

第一批只建设RevOS Core数据骨架，不接企微、不调用AI：

```text
backend/app/models/revos.py
backend/app/schemas/revos.py
backend/app/services/revos/customer_state.py
backend/app/services/revos/opportunity.py
backend/app/services/revos/arbitration.py
backend/app/api/v1/revos.py
backend/alembic/versions/<revision>_revos_core.py
backend/tests/test_revos_tenant_security.py
backend/tests/test_revos_opportunity.py
backend/tests/test_revos_state_history.py
```

建议逻辑对象：

- CustomerIdentity；
- CustomerStateHistory；
- Opportunity；
- Decision；
- WorkflowDefinition/Instance；
- ExecutionPlan；
- Action；
- Outcome；
- StrategyVersion。

MVP可以减少物理表数量，但必须保留不可变版本和关联语义。

## 7. 开发顺序

1. 建立Git基线；
2. 修复服务端租户隔离并增加安全测试；
3. 导出现有OpenAPI并与需求规格比较；
4. 新增RevOS Core迁移和模型；
5. 将Recovery改造成统一Opportunity Detector；
6. 增加触达仲裁器；
7. 增加心理策略和ExecutionPlan；
8. 增加人工审核；
9. 接内容生成API；
10. 接企微人工确认；
11. 接小程序、预约、到店、支付结果；
12. 增量归因与学习；
13. 用Retention场景验证复用能力。

## 8. 启动门槛

开始修改业务代码前，应满足：

- 源代码已经进入Git并完成基线提交；
- 43项测试继续通过；
- 生产/测试数据库已备份；
- 明确第一场景为高价值沉睡客户召回；
- 前端SaaS实际OpenAPI或测试环境可用；
- 租户隔离修复方案已确认；
- 所有迁移可回滚；
- 每批DeepSeek改动保持小范围并单独审查。

## 9. 最终判断

当前代码质量足以作为RevOS原地升级基座，不需要推倒重来。最大的短期风险不是AI能力，而是无版本控制、租户隔离不足和统一Opportunity缺失。

建议先完成“工程安全基线 + RevOS Core模型”，再进入AI内容、企微和小程序开发。
