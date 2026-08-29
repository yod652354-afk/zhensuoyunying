# ClinicOS → RevOS 转化升级总体开发规格

版本：V1.0  
日期：2026-08-29  
开发方式：使用 DeepSeek 一次性完整开发  
配套执行规格：《ClinicOS二期-企微人工审核执行闭环-DeepSeek开发规格》

> 交付口径：本文件中出现的“阶段/Phase”仅表示同一次完整开发中的内部依赖顺序和验证检查点，不代表分期交付。最终必须一次性交付本规格及《03-一次性完整开发任务》规定的全部核心能力。

---

## 1. 升级结论

本项目不是重新开发一套 RevOS，也不是在 ClinicOS 旁边建立一个新系统。

正确路线是：

> 保留 ClinicOS 已有的数据、API、任务、事件、实验、归因和运营后台，将其领域中心从“诊所功能模块”升级为“客户价值 → 经营机会 → 决策 → 执行 → 结果 → 增量收入”的 RevOS。

升级后的产品关系：

```text
RevOS：统一产品与经营智能平台
  ├─ RevOS Data Foundation：原 ClinicOS 数据底座
  ├─ Opportunity Engine：三种钱机会识别与排序
  ├─ Decision Engine：下一最佳动作与执行约束
  ├─ Workflow Engine：各经营场景工作流
  ├─ Execution Engine：人工协同、企微、小程序及后续渠道
  ├─ Outcome & Attribution：结果与增量收入归因
  └─ Learning Engine：策略版本、实验与效果学习
```

“ClinicOS”在升级完成后不再作为一套与 RevOS 并列的产品。它可以作为医疗诊所行业包、历史项目代号或兼容层存在。

---

## 2. 产品重新定义

### 2.1 旧 ClinicOS

```text
患者
→ 到店/预约/疗程/交易
→ Recovery / Retention / Growth
→ 任务
→ 员工执行
→ 报表
```

### 2.2 新 RevOS

```text
Customer
→ Customer Value State
→ Opportunity
→ Next Best Action
→ Workflow
→ Human-approved Execution
→ Outcome
→ Incremental Revenue
→ Learning
```

### 2.3 对外产品语言

- 未来的钱：获得新的收入机会；
- 现在的钱：保护正在发生的客户价值；
- 过去的钱：追回已经流失的客户价值。

### 2.4 对内技术语言

- Customer；
- Identity；
- Value State；
- Opportunity；
- Decision；
- Workflow；
- Action；
- Touch；
- Outcome；
- Attribution；
- Learning。

三种钱是 Opportunity 的分类，不是三套独立系统。

---

## 3. 升级原则

1. **原地演进**：修改现有代码库，禁止另建一套平行 RevOS 后端。
2. **数据兼容**：现有 Patient、Task、Campaign、Touch、Followup、Event 和 Attribution 数据必须保留。
3. **先兼容后重命名**：数据库物理表可阶段性保留旧名称，先统一领域接口，再决定物理迁移。
4. **一个机会中枢**：Recovery、Retention、Growth 只负责产生候选机会，不再直接各自驱动完整执行链。
5. **一个执行引擎**：不同场景通过 Workflow 配置，禁止复制 Agent 或任务系统。
6. **人在回路**：大健康场景的外部触达默认需要人工审核和必要的员工确认。
7. **增量证明**：总收入、点击和任务量不能替代增量归因。
8. **行业可扩展**：核心使用 Customer/Service/Plan；医疗语义放入 Clinic Industry Pack。
9. **先真实闭环再平台化**：先跑通沉睡召回，再复制到其他场景。
10. **不以AI生成作为核心资产**：文本和图片生成使用外部 API，核心资产是 Action→Outcome→Revenue 数据。
11. **复用既有前端API合同**：诊所SaaS的数据与API需求已经通过《ClinicOS_诊所SaaS数据与API接口完整需求规格_V1.0》下发。RevOS不得重新要求前端设计同一套接口；下一步是逐项验收、字段映射、联调和差异补齐。

---

## 4. 目标架构

```text
外部数据源
HIS / CRM / 收银 / 企微 / 小程序 / CSV
        │
        ▼
Connector & Identity Resolution
        │
        ▼
RevOS Data Foundation
Customer / Visit / Appointment / Service / Plan / Order / Payment
        │
        ▼
Customer Value State
生命周期 + 三种钱状态 + 价值等级 + 风险状态
        │
        ▼
Opportunity Engine
发现 / 去重 / 评分 / 冲突仲裁 / 产能约束
        │
        ▼
Decision Engine
Next Best Action / Channel / Timing / Strategy / Human Gate
        │
        ▼
Workflow Engine
沉睡召回 / 复诊超期 / No-show / 疗程中断 / 新客转化
        │
        ▼
Execution Engine
人工任务 / AI内容 / 审核 / 企微确认 / 小程序承接
        │
        ▼
Outcome & Attribution
回复 / 预约 / 到店 / 支付 / 增量收入 / ROI
        │
        ▼
Learning Engine
实验 / 策略版本 / 模板版本 / 效果更新
```

这里的 Connector 不是要求前端重新开发一套业务API。它是 RevOS 内部的适配层，用于消费既有 `/api/v1` Read/Write API、Webhook/Event 和增量同步合同，并将前端字段映射为 RevOS 标准经营事件。

既有诊所SaaS继续作为以下事实的主系统：患者资料、医生员工、服务项目、预约、到店、治疗计划、订单、支付、退款、套餐、回访、活动和产能。RevOS只保存经营判断所需特征、状态、机会、方案、动作、结果和必要快照。

---

## 5. ClinicOS 现有资产映射

| ClinicOS 现有资产 | RevOS 目标归属 | 处理方式 |
|---|---|---|
| Patient | Customer + Clinic Patient Extension | 保留表和API兼容，新增Customer领域服务 |
| Doctor/Staff | Actor/Owner + Clinic Extension | 保留 |
| Visit/Appointment | Journey Events | 保留 |
| TreatmentPlan/Package | Service Plan | 建立通用接口，保留医疗字段 |
| Order/Payment/Refund | Revenue Facts | 保留并加强可信数据源标记 |
| Recovery Service | Opportunity Detector | 改为候选机会生成器 |
| Retention Service | Opportunity Detector | 改为候选机会生成器 |
| Growth Campaign | Campaign Workflow/Experiment | 保留，不再等同未来的钱全部能力 |
| Task | Execution Task | 扩展关联 opportunity/workflow/action |
| Followup | Human Action/Response | 梳理语义后兼容 |
| Touch | Channel Action | 扩展内容版本、发送和回执字段 |
| Event | Domain Event | 增加 correlation/causation/schema_version |
| Attribution | Revenue Attribution | 加入归因窗口、版本和证据链 |
| ContentReview | Human Gate | 扩展机器检查与不可变内容版本 |
| MessageTemplate | Content Fallback | 保留，作为AI失败兜底 |
| Dashboard | Three-Money Cockpit | 重构数据来源为Opportunity与Outcome |

---

## 6. 新增核心模块

### 6.1 Customer Identity

解决手机号、企微、小程序和不同HIS客户ID的映射。稳定主键是 `customer_id`，其他身份均为有作用域、可变的 Identity。

### 6.2 Customer Value State

一个客户同时拥有：

- lifecycle_state：lead/new/active/in_service/at_risk/dormant/lost/reactivated；
- money_state：future/current/past；
- value_tier：S/A/B/C/D；
- risk_flags；
- state_reason_codes；
- state_changed_at。

状态必须有历史表，不能只保存当前值。

### 6.3 Opportunity Engine

所有 Detector 只产生标准候选机会：

```json
{
  "customer_id": "cus_xxx",
  "money_type": "past",
  "scenario_type": "dormant_recovery",
  "expected_revenue": 860,
  "priority_score": 78,
  "reason_codes": ["DORMANT_90_DAYS", "HIGH_VALUE"],
  "recommended_workflow": "dormant_recovery_v1"
}
```

中枢统一完成：

- 去重；
- 冲突检测；
- 频控；
- 合规排除；
- 机会价值排序；
- 门店及员工产能限制；
- 对照组保留；
- 机会过期。

### 6.4 Decision Engine

V1 为规则决策，不需要复杂 Agent 框架。

输出标准 Decision：

- 是否执行；
- 为什么；
- 推荐动作；
- 工作流；
- 渠道；
- 建议时间；
- 内容策略；
- 是否必须人工审核；
- 执行负责人；
- 停止条件；
- 升级人工条件。

### 6.5 Workflow Engine

工作流定义不得散落在各 service 的条件分支中。V1 可用数据库配置加代码 Handler，无需引入大型 BPM 平台。

```yaml
code: dormant_recovery_v1
trigger: opportunity.approved
steps:
  - generate_content
  - machine_compliance_check
  - human_review
  - create_wecom_send_task
  - member_confirm_send
  - wait_for_response
  - sync_appointment_visit_payment
  - calculate_attribution
stop_conditions:
  - dnc
  - complaint
  - opportunity_expired
  - customer_converted
```

### 6.6 Execution Engine

包括：

- 人工任务；
- AI文本/图片 API；
- 模板兜底；
- 自动合规检查；
- 人工审核；
- 企微成员确认；
- 小程序安全承接；
- 回复、预约、到店、支付回流。

具体开发按配套《企微人工审核执行闭环》规格实施。

### 6.7 Outcome & Attribution

统一 Outcome，不再由 Task、Followup、Touch 分别表达最终结果。Revenue Attribution 必须保留从机会到交易的完整证据链。

### 6.8 Learning Engine

V1 不自动修改生产规则，只计算并推荐：

- 场景 × 客群 × 策略；
- 内容版本；
- 渠道；
- 发送时间；
- 审核通过率；
- 回复/预约/到店/支付；
- 投诉与DNC；
- 增量收入和ROI。

所有策略权重变更先由人批准。

---

## 7. 数据模型增量

必须新增或规范化：

- `customer_identities`；
- `customer_state_history`；
- `opportunities`；
- `opportunity_evidence` 或标准 `reason_codes/context_snapshot`；
- `decisions`；
- `workflow_definitions`；
- `workflow_instances`；
- `actions`；
- `content_drafts`；
- 扩展 `content_reviews`；
- `interaction_sessions`；
- `outcomes`；
- 扩展 `attributions`；
- `strategy_performance`。

### 7.1 关键关联

```text
customer
  ├─ identities
  ├─ state_history
  └─ opportunities
       ├─ decision
       ├─ workflow_instance
       ├─ actions/tasks/touches
       ├─ outcomes
       └─ attributions
```

### 7.2 Action 标准记录

每个实际动作至少记录：

- action_type；
- actor_type/actor_id；
- channel；
- strategy_code；
- content_version；
- context_snapshot；
- occurred_at；
- cost；
- status；
- correlation_id；
- causation_id。

---

## 8. API 迁移策略

### 8.1 保留

现有 `/api/v1/patients`、appointments、visits、orders、tasks、campaigns、events 等接口继续可用。

### 8.2 新增

- `/api/v1/customers`：RevOS统一客户视图；
- `/api/v1/customer-identities`；
- `/api/v1/customer-states`；
- `/api/v1/opportunities`；
- `/api/v1/decisions`；
- `/api/v1/workflows`；
- `/api/v1/actions`；
- `/api/v1/outcomes`；
- `/api/v1/attribution-traces`。

### 8.3 兼容规则

- Patient API 内部调用 Customer Domain Service；
- 原 Recovery Pool API 可暂时转换为 `money_type=past` 的 Opportunity 查询；
- Retention 超期列表转换为 `money_type=current` 的候选机会；
- Growth Campaign 保留活动管理，不再承担未来机会的完整定义；
- 原 Task 新增 `opportunity_id/action_id/workflow_instance_id`，旧数据允许为空；
- 所有响应增加 `schema_version` 或通过版本化接口管理破坏性变化。

---

## 9. 前端信息架构升级

### 9.1 一级导航

1. 三种钱驾驶舱；
2. 经营机会；
3. 今日执行；
4. 内容审核；
5. 客户；
6. 实验与归因；
7. 数据与连接；
8. 合规与审计；
9. 系统配置。

### 9.2 三种钱驾驶舱

每类钱统一展示：

- 机会客户数；
- 机会预计金额；
- 待执行金额；
- 执行中金额；
- 已赢得增量收入；
- 机会迁移；
- 最大漏损节点；
- 数据质量及归因可信度。

不得再将任务预计价值直接显示为已产生增量收入。

### 9.3 经营机会池

统一列表按 money_type、scenario、价值、优先级、状态、门店和负责人筛选。进入详情可查看：证据、Decision、Workflow、Action、Outcome 和 Attribution 时间线。

---

## 10. 品牌和代码命名迁移

### 10.1 第一阶段

- UI 主品牌改为 RevOS；
- 登录页显示“RevOS 大健康经营智能平台”；
- README 增加升级说明；
- 包名、数据库名和环境变量暂不强制全面更换；
- API 保持兼容。

### 10.2 第二阶段

- 新模块统一使用 `revos` 领域命名；
- 原有 `recovery/retention/growth` service 转为 detectors/workflows；
- 文档、OpenAPI 和部署名称统一；
- 提供数据迁移与回滚方案。

### 10.3 第三阶段

- ClinicOS 变成 `clinic` Industry Pack；
- 通用 Core 不依赖 diagnosis、prescription 等医疗专属字段；
- 新行业通过 Industry Pack 提供字段、规则、工作流和模板。

不要第一天全局机械替换 `ClinicOS` 字符串，这会产生无业务价值的风险。

---

## 11. 一次性开发的内部实施顺序

### Phase 0：代码和数据审计（1周）

输出：

- 实际代码目录与文档声明对照；
- 现有43项测试真实结果；
- 数据表、API、任务和事件依赖图；
- 多租户隔离检查；
- 重复概念及废弃候选；
- 迁移风险清单。
- 对照既有API需求规格逐项填写A01-A30验收状态；
- 获取前端实际OpenAPI 3.1文件、测试环境和字段映射；
- 输出“已实现/部分实现/未实现/不支持/需要补齐”差异矩阵。

停止条件：如果一期代码、迁移或测试不完整，先修复基线，不进入功能开发。

本阶段不得重新发明患者、预约、到店、订单等接口。只有实际接口未满足既有合同或RevOS新增领域确有需要时，才提交最小增量变更。

### Phase 1：RevOS Core（2–3周）

- Customer Identity；
- Customer Value State；
- Opportunity；
- Decision；
- Workflow Instance；
- Action/Outcome；
- 事件规范；
- 兼容层。

验收：原三大引擎产生的结果可转换为统一 Opportunity，旧功能和测试不回退。

### Phase 2：首个执行闭环（4–6周）

场景：高价值沉睡客户召回。

- 内容生成 API；
- 自动检查；
- 人工审核；
- 企微员工确认；
- 小程序行为；
- 预约/到店/支付；
- Treatment/Holdout 归因。

验收：真实门店跑通完整证据链。

### Phase 3：第二个工作流（2–3周）

建议选择复诊超期或疗程中断。必须仅增加 Detector、Policy 和 Workflow 配置；如果需要复制一套执行代码，说明 Core 抽象失败，应停止并重构。

### Phase 4：生产化试点（4–8周）

- PostgreSQL生产验证；
- 持久队列和Outbox；
- 多租户安全；
- 监控告警；
- 备份恢复；
- 连接器；
- 10–30家试点；
- 自助接入初版。

### Phase 5：行业平台化

- Clinic Industry Pack；
- 康复/口腔等第二行业包；
- Workflow Registry；
- 策略效果 Benchmark；
- 连锁总部能力；
- 开发者能力后置。

---

## 12. DeepSeek 总任务提示词

以下内容作为总任务背景，不要要求 DeepSeek 一次完成全部代码：

```text
目标：在现有 ClinicOS 单一代码库中完成向 RevOS 的兼容式升级。

RevOS 的核心链路是：Customer → Value State → Opportunity → Decision → Workflow → Action → Outcome → Incremental Revenue。

ClinicOS 已有 Patient、Visit、Appointment、TreatmentPlan、Order、Payment、Task、Touch、Followup、Campaign、Experiment、Event、Attribution 等资产。必须优先复用，禁止新建平行后端或重写系统。

Recovery、Retention、Growth 应改造成统一 Opportunity Engine 的 Detector 和 Workflow，不得继续各自建设执行系统。“未来/现在/过去的钱”是 Opportunity 分类。

外部触达默认采用：AI生成 → 自动检查 → 人工审核 → 员工企微确认 → 结果回流。未经审核不得触达；内容修改后必须重新审核；DNC、投诉、未授权、频控必须在实际发送前再次检查。

开发要求：
1. 先审计现有代码和测试，输出事实，不根据README假设实现存在。
2. 每次只完成一个有边界的任务，先列出修改文件和兼容策略。
3. 数据库变更使用Alembic，迁移必须可回滚。
4. 保护现有数据、API和测试。
5. 服务端强制多租户权限，不能信任客户端租户ID。
6. 外部调用具备超时、幂等、重试分类、日志脱敏和模板兜底。
7. 不引入复杂Agent框架，不训练模型，文本/图片使用可替换API。
8. 所有Action、Outcome和Attribution具备完整correlation_id与证据链。
9. 每个功能必须同时交付单元测试、集成测试、迁移说明和风险说明。
10. 未经明确任务要求，不做全局重命名、UI美化或无关重构。
```

---

## 13. Definition of Done

只有同时满足以下条件，才能宣布 ClinicOS 已完成向 RevOS 的完整转化：

1. Recovery、Retention、Growth 均可输出标准 Opportunity；
2. 三种钱驾驶舱数据来自统一 Opportunity/Outcome，而非三套独立计算；
3. 至少两个经营场景复用同一 Decision、Workflow 和 Execution 基础设施；
4. 内容生成是可替换 Provider；
5. 所有客户外部触达均经过合规检查和人工审核；
6. 企微发送具有实际执行人、内容版本和发送证据；
7. 小程序和线下系统可以回流预约、到店、支付；
8. 任意归因收入均可追溯完整链路；
9. 对照组和增量口径真实运行；
10. 多租户隔离、幂等、队列、审计、监控通过生产级验证；
11. 原 ClinicOS 主要功能、数据和 API 未因升级丢失；
12. 至少一家真实门店完成闭环验收。

---

## 14. 最终产品公式

```text
RevOS
= ClinicOS 数据与工作流底座
+ 三种钱经营模型
+ Opportunity Engine
+ Decision & Workflow Engine
+ 人工审核的 AI Execution Engine
+ Outcome & Revenue Attribution
+ Action→Outcome 学习数据
```

本次升级最重要的结果不是更换品牌名称，而是把系统的中枢从“功能和任务”迁移到“经营机会和增量结果”。

---

## 15. 持续学习与进化架构

RevOS 的“学习”不得实现为大模型自行修改代码、规则或数据库配置。正式机制是：

```text
Context Snapshot
→ Decision Version
→ Executed Action
→ Customer Response
→ Business Outcome
→ Incremental Revenue
→ Strategy Evaluation
→ Human-approved Deployment
```

### 15.1 学习记录的最低完整性

每个进入执行的 Opportunity 必须冻结以下快照：

- 客户当时的生命周期、三种钱、价值等级和风险状态；
- Detector、评分公式、Decision Policy 和 Workflow 版本；
- 所有候选动作、最终动作和选择原因；
- AI模型、Prompt、模板、图片和策略版本；
- 自动检查结果、人工审核及人工修改；
- 实际执行渠道、时间、人员、优惠和成本；
- 客户回复、小程序行为、预约、到店、支付、退款、DNC和投诉；
- 实验组别、观察窗口、归因版本及增量结果。

禁止用事后变化的客户当前档案覆盖决策时快照。

### 15.2 Strategy Registry

新增统一策略注册中心，管理：

- detector_rule；
- scoring_formula；
- decision_policy；
- workflow_definition；
- content_strategy；
- prompt_template；
- message_template；
- timing_policy；
- channel_policy；
- prediction_model。

所有策略具有：`code`、`version`、`status`、`effective_from/to`、`owner`、`change_reason`、`approval_record`、`rollback_version`。

状态统一为：

```text
draft → offline_validated → shadow → experiment → limited_release → active → retired/rolled_back
```

生产记录只能引用不可变版本；修改策略必须创建新版本。

### 15.3 Experiment Gate

任何可能影响客户触达的新规则、策略、Prompt、模型或工作流，默认必须经过：

1. 离线历史数据回放；
2. 影子运行，不执行真实动作；
3. 运营/合规人员批准；
4. 小流量 Treatment/Holdout 或 A/B 实验；
5. 最低样本量和观察窗口；
6. 收益指标与护栏指标同时通过；
7. 逐步放量；
8. 持续监控和可回滚。

样本不足时只允许输出方向性结论，不得标记为平台最佳策略。

### 15.4 Shadow Mode

新规则或模型在影子模式中只输出建议：

```text
production_decision：实际执行
shadow_decision：只记录、不执行
```

真实结果回来后，系统比较两者在机会覆盖、增量价值、投诉风险和成本上的表现。影子模型不得创建 Task、Touch、优惠或任何外部动作。

### 15.5 Performance Engine

按以下维度计算策略效果：

- 行业、组织、门店；
- money_type、scenario_type；
- lifecycle_state、value_tier；
- strategy、channel、timing；
- content/prompt/model/workflow版本；
- 人工审核是否修改；
- Treatment/Holdout 分组。

指标包括：样本量、送达、回复、预约、到店、支付、退款、DNC、投诉、增量收入、增量贡献、ROI、置信区间和数据质量等级。

### 15.6 三层学习

```text
平台基线
→ 行业策略
→ 门店个性化
```

新门店使用平台和行业先验；本店积累足够有效样本后才启用本店参数。跨门店只共享满足授权和隐私要求的统计规律，不共享其他门店的客户级数据。

### 15.7 目标函数与护栏

优化目标不得只是点击率、预约率或总收入：

```text
Strategy Value
= Incremental Gross Profit
- Discount Cost
- Channel Cost
- AI Cost
- Human Cost
- Complaint/DNC Risk Cost
```

硬性护栏：

- 投诉或DNC超过阈值自动暂停；
- 合规规则不得由模型修改；
- 新版本不得直接全量发布；
- 不确定发送状态不得重复触达；
- 数据质量不足不得自动学习；
- 效果或稳定性显著下降自动回滚或降级；
- 自动建议不得自动成为生产规则，除非该策略类别已被明确批准自动化。

### 15.8 学习模块数据表

新增或扩展：

- `strategy_definitions`；
- `strategy_versions`；
- `decision_candidates`；
- `context_snapshots`；
- `strategy_assignments`；
- `strategy_performance`；
- `model_registry`；
- `model_evaluations`；
- `deployment_releases`；
- `rollback_records`；
- 扩展 experiments/assignments/attributions。

MVP 可合并部分物理表，但上述逻辑对象和不可变版本关系必须存在。

### 15.9 进化阶段

1. **规则与人工建议**：系统计算效果并建议调整，人批准；
2. **受控策略推荐**：在已批准动作集合中推荐策略、渠道和时间；
3. **预测与Uplift模型**：预测干预后与不干预的转化差异；
4. **分风险自动化**：低风险稳定策略逐步自动，高风险始终人工门控。

第一阶段禁止直接训练所谓“收入大模型”。优先积累标准化、可归因的 Action→Outcome 数据。

### 15.10 学习能力验收

RevOS 必须能够回答：

1. 为什么当时选择这个客户和动作？
2. 使用了哪个规则、评分、策略、Prompt和模型版本？
3. 人工修改了什么？
4. 客户和业务最终发生了什么？
5. 相对对照组产生了多少增量价值？
6. 哪个版本在什么客群和场景更有效？
7. 新版本经过了哪些验证和批准？
8. 当前版本失败时能否一键回滚？

缺少任何一项，不得宣称系统已经形成持续学习闭环。
