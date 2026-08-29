# ClinicOS 二期开发规格

## 企微人工审核执行闭环（DeepSeek 开发版）

版本：V1.0  
日期：2026-08-29  
适用对象：产品负责人、后端开发、前端开发、小程序开发、测试人员、使用 DeepSeek 辅助开发的工程团队

> 交付口径：本文件中的“阶段A-F”仅用于同一次开发任务中的内部编码和验证顺序，不代表多期交付。企微审核闭环必须与RevOS Core、客户状态机、Opportunity、ExecutionPlan、结果回流和归因学习一次性完成。

---

## 1. 文档目标

本文件用于指导 ClinicOS 二期开发，在一期“数据底座 + 三种钱经营引擎 + 任务系统 + 实验归因”基础上，增加一条可在真实门店运行的受控执行闭环：

```text
识别经营机会
→ 生成营销内容
→ 自动合规检查
→ 人工审核
→ 创建企微发送任务
→ 客户负责人确认发送
→ 小程序/预约/到店/支付结果回流
→ 增量收入归因
```

本期采用“人在回路”的执行模式。AI 负责生成建议和素材，系统负责检查、频控、留痕和归因，人负责批准并完成企微发送。

### 1.0 既有前端API前提

诊所SaaS前端/业务系统的数据接口已由《ClinicOS_诊所SaaS数据与API接口完整需求规格_V1.0》约定。本开发不得重新设计患者、预约、到店、疗程、订单、支付、退款、套餐、回访、任务、活动等基础接口。

实施动作是：

1. 获取前端团队实际交付的 OpenAPI 3.1 文件和测试环境；
2. 按原规格 A01-A30 逐项验收；
3. 建立源字段到 RevOS 字段的映射；
4. 联调 Read API、Write API、Webhook 和 `updated_since + cursor` 补偿同步；
5. 只针对实际缺口提交最小补充需求。

RevOS内部 Adapter 负责适配既有API，不代表再要求前端建设第二套接口。

### 1.1 本期成功标准

至少在一家真实门店、一个真实经营场景中，完整跑通：

1. 从真实客户数据产生经营机会；
2. AI 生成文案及可选图片；
3. 系统完成规则检查；
4. 老板或店长完成人工审核；
5. 客户归属员工在企微确认发送；
6. 系统记录发送结果、客户行为、预约、到店和支付；
7. 实验组与对照组可计算增量结果；
8. 任意一笔系统宣称的增量收入均可追溯到机会、动作、触达和结果。

### 1.2 本期不做

- 不训练自有大模型或图像模型；
- 不建设通用 Agent 平台；
- 不做完全无人审核的企微自动营销；
- 不做开放式医疗问诊机器人；
- 不生成诊断、处方或疗效承诺；
- 不重做 HIS、电子病历、支付和完整 CRM；
- 不同时上线大量经营场景；
- 不把页面浏览、总成交或自然回款直接算成 AI 增量收入。

---

## 2. 首期场景

首期只开发“高价值沉睡客户召回”。其他场景必须通过配置和工作流复用接入，不得复制一套新引擎。

### 2.1 进入条件

默认规则，可按门店配置：

- 最近 60 天没有到店或消费；
- 历史累计消费不低于门店阈值；
- 有有效联系方式；
- `consent_status = granted`；
- `dnc = false`；
- `complaint_flag = false`；
- 最近 14 天没有主动营销触达；
- 当前不存在同类未完成机会或任务。

### 2.2 排除条件

- 明确拒绝联系；
- 投诉或无效联系方式；
- 不符合敏感个人信息使用授权；
- 最近已触达；
- 当前存在医疗争议或人工特殊标记；
- 已进入对照组；
- 门店或员工当日触达产能已满。

### 2.3 机会评分 V1

V1 使用可解释规则，不调用大模型进行数值评分：

```text
priority_score =
  historical_value_score * 0.30
  + recency_score * 0.20
  + visit_frequency_score * 0.15
  + unfinished_package_score * 0.15
  + historical_response_score * 0.10
  + contactability_score * 0.10
  - recent_touch_penalty
  - complaint_risk_penalty
```

同时保存 `reason_codes`，例如：

```json
[
  "DORMANT_90_DAYS",
  "HIGH_HISTORICAL_REVENUE",
  "PACKAGE_REMAINING",
  "VALID_WECOM_CONTACT"
]
```

---

## 3. 统一领域模型

### 3.1 核心对象

| 对象 | 作用 |
|---|---|
| Customer | 稳定客户主体，沿用一期 Patient，并逐步向 Customer 抽象 |
| CustomerIdentity | 手机号、企微 external_userid、openid、unionid 等可变身份 |
| Opportunity | 系统发现的一次经营机会 |
| ContentDraft | AI 或模板生成的内容草稿及版本 |
| ContentReview | 自动检查及人工审核记录 |
| ExecutionTask | 需要员工执行的企微发送任务，可复用一期 Task |
| Touch | 一次实际客户触达 |
| InteractionSession | 企微卡片到小程序行为的安全会话 |
| CustomerEvent | 点击、预约、到店、支付等行为事实 |
| Outcome | 机会最终产生的业务结果 |
| Attribution | 结果与触达、实验、机会之间的归因关系 |

### 3.2 禁止的身份设计

不得把手机号定义为数据库主键或“永远不变的唯一标识”。

正确设计：

```text
customer_id：内部稳定主键
  ├─ mobile：可变、可缺失、可有多个历史版本
  ├─ external_userid：企业范围内身份
  ├─ openid：小程序应用范围内身份
  └─ unionid：满足微信开放平台条件时使用
```

---

## 4. 数据库设计

以下字段为最低要求。表名可与现有代码命名保持一致，但语义不得改变。

### 4.1 customer_identities

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string/uuid | 主键 |
| organization_id | string | 租户 |
| store_id | string nullable | 门店 |
| customer_id | string | 客户 |
| identity_type | enum | mobile/external_userid/openid/unionid |
| identity_value_encrypted | text | 加密值 |
| identity_hash | string | 匹配与唯一索引用哈希 |
| provider | string nullable | wecom/wechat/other |
| app_scope | string nullable | corp_id/app_id 等作用域 |
| is_primary | bool | 是否当前主标识 |
| verified_at | datetime nullable | 验证时间 |
| valid_from | datetime | 生效时间 |
| valid_to | datetime nullable | 失效时间 |
| created_at/updated_at | datetime | 审计字段 |

唯一约束建议：

```text
(organization_id, identity_type, identity_hash, app_scope, valid_to is null)
```

### 4.2 opportunities

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | `opp_` 前缀稳定 ID |
| organization_id/store_id | string | 租户及门店 |
| customer_id | string | 客户 |
| money_type | enum | future/current/past |
| scenario_type | string | dormant_recovery 等 |
| lifecycle_state | string | 产生机会时客户状态 |
| status | enum | candidate/qualified/approved/executing/won/lost/expired/suppressed |
| priority_score | decimal | 0–100 |
| expected_revenue | decimal | 预计收入，不等于已归因收入 |
| probability | decimal | 预计成功概率 |
| expected_cost | decimal | 预计成本 |
| reason_codes | json | 可解释原因 |
| context_snapshot | json | 产生机会时的最小化上下文快照 |
| workflow_code | string | `dormant_recovery_v1` |
| experiment_id | string nullable | 实验 |
| experiment_group | enum nullable | control/treatment_a/treatment_b |
| owner_staff_id | string nullable | 负责人 |
| detected_at | datetime | 识别时间 |
| expires_at | datetime | 过期时间 |
| created_at/updated_at | datetime | 审计字段 |

唯一去重建议：同一客户、同一场景、同一有效周期只允许一个活动机会。

### 4.3 content_drafts

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 草稿 ID |
| opportunity_id | string | 所属机会 |
| version | integer | 版本号，从1递增 |
| generation_mode | enum | ai/template/manual |
| model_provider/model_name | string nullable | 生成服务记录 |
| prompt_template_code/version | string nullable | Prompt 版本 |
| strategy_code | string | 关怀、权益提醒等策略 |
| input_snapshot | json | 脱敏输入快照 |
| title | string | 标题 |
| wecom_text | text | 企微正文 |
| image_url | string nullable | 可选图片 |
| mini_program_config | json nullable | 页面和卡片配置 |
| risk_flags | json | 模型自报及规则命中项 |
| generation_latency_ms | integer nullable | 延迟 |
| input_tokens/output_tokens | integer nullable | 用量 |
| estimated_cost | decimal nullable | 成本 |
| status | enum | draft/check_failed/pending_review/approved/rejected/superseded |
| created_at | datetime | 创建时间 |

### 4.4 content_reviews

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 审核 ID |
| content_draft_id | string | 草稿版本 |
| review_type | enum | machine/human |
| decision | enum | pending/approved/rejected/changes_requested |
| risk_level | enum | low/medium/high/blocked |
| rule_results | json | 自动规则详情 |
| reviewer_id | string nullable | 人工审核人 |
| review_note | text nullable | 意见 |
| reviewed_at | datetime nullable | 审核时间 |
| content_hash | string | 防止审核后内容被替换 |

要求：任何内容修改后必须产生新版本并重新审核；不得修改已批准版本正文。

### 4.5 touches 扩展

增加：

- opportunity_id；
- content_draft_id；
- task_id；
- channel_account_id；
- send_mode：manual/assisted；
- external_message_id；
- delivery_status：pending/created/waiting_member_confirmation/sent/delivered/failed/unknown；
- failure_code/failure_message；
- confirmed_by；
- confirmed_at；
- sent_at；
- content_hash；
- correlation_id。

### 4.6 interaction_sessions

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 对外使用的随机会话 ID |
| opportunity_id/touch_id/content_draft_id | string | 服务端关联 |
| customer_id | string | 目标客户 |
| token_hash | string | ticket 哈希，不保存明文 |
| expires_at | datetime | 过期时间 |
| first_opened_at | datetime nullable | 首开 |
| bound_openid_identity_id | string nullable | 首次验证后绑定 |
| status | enum | issued/opened/expired/revoked |

企微卡片只携带随机 ticket。不得携带手机号、customer_id、task_id、campaign_id 或 offer_id。

### 4.7 outcomes

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 结果 ID |
| opportunity_id | string | 机会 |
| customer_id | string | 客户 |
| outcome_type | enum | replied/interested/appointment/visited/paid/dnc/complaint/no_response |
| source_event_id | string | 原始事实事件 |
| occurred_at | datetime | 发生时间 |
| revenue_amount | decimal nullable | 交易金额，不等于增量收入 |
| metadata | json | 补充信息 |

---

## 5. 状态机

### 5.1 Opportunity 状态

```text
candidate
→ qualified
→ approved
→ executing
→ won / lost / expired / suppressed
```

对照组机会可进入 `approved`，但不得生成内容、任务和触达；只观察自然结果。

### 5.2 内容状态

```text
draft
→ 自动检查
  ├─ check_failed
  └─ pending_review
       ├─ rejected
       ├─ changes_requested → 新版本 draft
       └─ approved
```

### 5.3 企微执行状态

```text
pending
→ content_approved
→ waiting_member_confirmation
→ sent
→ delivered / failed / unknown
→ responded
→ appointment_created
→ visited
→ paid
→ attributed
```

状态变更必须写事件，不允许仅覆盖最终状态。

---

## 6. 内容生成服务

### 6.1 设计原则

内容生成属于可替换外部能力，不是 ClinicOS 核心引擎。

实现统一接口：

```python
class ContentGenerationProvider:
    def generate_text(self, request: TextGenerationRequest) -> TextGenerationResult: ...
    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...
```

首期可接一个文本模型和一个图片生成 API。所有供应商配置必须来自环境变量或密钥管理服务，不得写入代码和数据库明文字段。

### 6.2 最小输入

模型只接收经营所需的脱敏特征，例如：

```json
{
  "scenario": "dormant_recovery",
  "dormant_days_bucket": "90-180",
  "historical_value_level": "high",
  "service_category": "颈肩调理",
  "package_remaining_bucket": "1-3",
  "last_response": "replied",
  "store_display_name": "某某健康门店",
  "doctor_display_name": "周医生",
  "strategy": "care_and_rights_reminder"
}
```

不得发送：手机号、身份证号、住址、完整病历、具体诊断、处方、检查报告、无必要的姓名。

### 6.3 结构化输出

```json
{
  "title": "近况关怀",
  "wecom_text": "您好，最近还好吗？周医生看到您有一段时间没来门店了……",
  "image_prompt": "温和、专业的大健康关怀海报……",
  "mini_program": {
    "card_title": "查看本次关怀与可用权益",
    "page_code": "customer_care_offer"
  },
  "strategy_code": "care_and_rights_reminder",
  "risk_flags": []
}
```

服务端必须执行 JSON Schema 校验、长度校验和枚举校验。解析失败可重试一次，仍失败则使用已审核模板兜底。

### 6.4 内容禁止项

- 保证治愈、根治、百分百有效；
- 伪造案例、人数、名额或医生结论；
- 根据病情制造恐惧；
- 未经证实的稀缺性和社会证明；
- 暴露敏感健康信息；
- 使用未经审核的价格、优惠、券和有效期；
- 暗示系统已代替医生作出医疗判断。

---

## 7. 自动检查与人工审核

### 7.1 自动检查顺序

1. 内容结构检查；
2. 敏感信息泄露检查；
3. 医疗广告风险词；
4. 绝对化、疗效承诺和恐惧诱导；
5. 优惠、价格和有效期是否来自门店配置；
6. 虚假稀缺性或未经授权的统计数字；
7. 客户 Consent/DNC/投诉状态；
8. 14天频控；
9. 客户和员工当日触达上限；
10. 内容哈希生成。

`blocked` 风险不得通过普通审核员强制发送，需要管理员处理。

### 7.2 人工审核页

必须展示：

- 客户脱敏信息；
- 为什么产生该机会；
- 三种钱分类；
- 预计价值及评分原因；
- 文案、图片、小程序卡片预览；
- 内容版本、生成方式和策略；
- 自动检查结果；
- Consent、DNC、投诉、近期触达；
- 计划发送员工和发送时间；
- 实验组别；
- 批准、要求修改、驳回操作。

### 7.3 批量审核限制

只有以下条件全部相同时可批量审核：

- 同一门店；
- 同一场景；
- 同一内容模板或相同内容哈希；
- 同一优惠配置；
- 风险等级为 low；
- 不包含客户特定敏感健康信息。

个性化正文不同的内容默认逐条审核，MVP 不应为了效率绕过审核。

---

## 8. 企业微信执行层

### 8.1 默认模式

首期默认：

```text
系统创建发送任务
→ 企微成员收到待确认任务
→ 成员在企微客户端确认发送
→ 系统同步或人工回填发送状态
```

只有在真实环境验证相关接口明确允许、且符合平台规则后，才允许增加自动模式。不得根据文档猜测实现“自动1对1外部联系人发送”。

### 8.2 WeCom Gateway 职责

- access_token 获取、缓存和失效刷新；
- external_userid 与 customer_id 映射；
- 创建群发或成员确认任务；
- 文字、小程序卡片及可选图片素材；
- 查询/接收发送结果；
- 限流、幂等和失败处理；
- 按组织、门店和企业账号隔离凭证；
- 原始响应脱敏存档；
- 统一错误码映射。

### 8.3 重试规则

- 鉴权失败：刷新 token 后重试一次；
- 网络超时和明确可重试错误：指数退避；
- 频控、无权限、无客户关系、拒收：不得盲目重试；
- 不确定是否成功：先查询状态，禁止直接重复发送；
- 所有发送使用幂等键：`touch_id + content_hash`。

### 8.4 人工发送确认

员工端任务展示：

- 客户姓名或脱敏名；
- 审核通过的固定内容预览；
- 发送原因；
- 建议发送时间；
- 复制文字、打开企微、确认发送；
- 已发送、发送失败、客户不适合联系；
- 客户回复结果。

员工不得直接编辑已经批准的正文。若需修改，必须创建新内容版本并重新审核。

---

## 9. 小程序安全与行为回流

### 9.1 认证原则

不得在小程序代码中嵌入长期 `X-API-Key`。

推荐流程：

```text
wx.login
→ 小程序服务端换取微信会话
→ ClinicOS 签发短期访问令牌
→ ticket + 短期令牌访问专属内容
```

### 9.2 获取专属内容

`GET /api/v1/mp/sessions/{ticket}/offer`

返回：

- 公开展示内容；
- 页面配置；
- interaction_session_id；
- 允许的 CTA；
- 过期时间。

不返回内部 customer_id、task_id、手机号、医疗敏感信息。

### 9.3 行为上报

`POST /api/v1/mp/events`

```json
{
  "event_id": "client_generated_uuid",
  "interaction_session_id": "int_xxx",
  "event_type": "page_view",
  "occurred_at": "2026-08-29T10:00:00+08:00",
  "page_code": "customer_care_offer",
  "payload": {
    "duration_seconds": 12
  }
}
```

允许事件：`page_view`、`cta_click`、`appointment_submit`、`coupon_receive`、`share`。支付结果必须由可信服务端回调或 ClinicOS 数据同步产生，不能信任客户端上报 `payment_success`。

---

## 10. 后端 API

统一前缀：`/api/v1`。所有接口执行组织和门店权限校验。

### 10.1 Opportunity

- `POST /opportunities/detect/dormant-recovery`：运行识别任务；
- `GET /opportunities`：筛选、分页、排序；
- `GET /opportunities/{id}`：详情及时间线；
- `PATCH /opportunities/{id}/suppress`：人工抑制；
- `POST /opportunities/{id}/assign-experiment`：分组；
- `POST /opportunities/{id}/generate-content`：为 Treatment 组生成内容。

### 10.2 Content

- `GET /content-drafts/{id}`；
- `POST /content-drafts/{id}/regenerate`；
- `POST /content-drafts/{id}/request-change`；
- `POST /content-drafts/{id}/machine-check`；
- `POST /content-drafts/{id}/review`；
- `GET /content-drafts/{id}/versions`。

审核请求：

```json
{
  "decision": "approved",
  "review_note": "内容及权益有效期已核对",
  "expected_content_hash": "sha256:xxx"
}
```

若哈希不一致返回 `409 CONTENT_CHANGED`。

### 10.3 Execution

- `POST /content-drafts/{id}/create-send-task`；
- `GET /send-tasks`；
- `POST /send-tasks/{id}/prepare-wecom`；
- `POST /send-tasks/{id}/confirm-sent`；
- `POST /send-tasks/{id}/mark-failed`；
- `POST /send-tasks/{id}/record-response`；
- `GET /touches/{id}`。

### 10.4 Outcome 与归因

- `POST /outcomes/sync`：可信内部同步；
- `GET /opportunities/{id}/outcomes`；
- `POST /experiments/{id}/calculate`；
- `GET /experiments/{id}/metrics`；
- `GET /attributions/{id}/trace`。

---

## 11. 事件规范

至少发布：

```text
opportunity.detected
opportunity.qualified
opportunity.suppressed
content.generated
content.machine_checked
content.review_approved
content.review_rejected
send_task.created
touch.waiting_confirmation
touch.sent
touch.failed
customer.responded
mini_program.opened
appointment.created
visit.completed
payment.completed
opportunity.won
opportunity.lost
attribution.calculated
```

事件统一包含：

```json
{
  "event_id": "evt_xxx",
  "event_type": "touch.sent",
  "organization_id": "org_xxx",
  "store_id": "store_xxx",
  "occurred_at": "ISO8601",
  "actor": {"type": "staff", "id": "staff_xxx"},
  "object": {"type": "touch", "id": "tou_xxx"},
  "correlation_id": "opp_xxx",
  "causation_id": "evt_previous",
  "data": {}
}
```

---

## 12. 实验与收入归因

### 12.1 实验要求

- 入组必须发生在生成和发送内容之前；
- 对照组不得触达；
- 分组后保存不可变快照；
- 记录样本污染，如员工私下联系；
- 预先定义观察窗口和主要指标；
- 小样本只报告方向性，不宣称显著。

### 12.2 指标

主要指标：观察窗口内到店率或支付率。  
次要指标：回复率、预约率、小程序打开率。  
护栏指标：DNC、投诉、发送失败率、人工审核时间。

```text
Incremental Rate = Treatment Rate - Control Rate
Incremental Customers = Eligible Treatment Population × Incremental Rate
Incremental Revenue = Incremental Customers × 预先定义的合格收入均值
Incremental Contribution = Incremental Revenue × 毛利率 - 触达及优惠成本
ROI = Incremental Contribution / 执行成本
```

不得将 Treatment 组所有收入相加后称为增量收入。

### 12.3 追溯链

每笔归因结果必须能返回：

```text
Experiment
→ Opportunity
→ Content Version
→ Human Review
→ Send Task
→ Touch
→ Response/Behavior
→ Appointment
→ Visit
→ Order/Payment
→ Attribution Result
```

---

## 13. 权限与审计

| 角色 | 权限 |
|---|---|
| Boss/Admin | 配置规则、审核、查看归因、管理企微账号 |
| Manager | 审核本门店内容、分配任务、查看门店结果 |
| Staff | 查看本人任务、执行发送、记录回复；不得审批自己的高风险内容 |
| Auditor | 只读查看内容、审核、触达和归因证据 |

必须记录：登录、查看敏感信息、内容生成、修改、审核、发送、DNC变更、导出、身份合并和归因重算。

所有查询必须以服务端解析的 `organization_id` 过滤，禁止信任客户端传入的租户 ID。

---

## 14. 非功能要求

### 14.1 安全

- 密钥不得入库明文、进入日志或提交到 Git；
- 手机号等标识加密存储，匹配使用单独哈希；
- 日志默认脱敏；
- ticket 高熵、短期有效、可撤销；
- 图片和反馈文件限制类型、大小并使用对象存储；
- 防止越权读取其他客户内容；
- 管理操作具备 CSRF/XSS/注入防护；
- 正式上线前进行隐私、医疗广告和安全专项审查。

### 14.2 可靠性

- 所有外部调用设置超时；
- 发送和事件上报支持幂等；
- 不确定发送状态不得自动重复触达；
- 生产环境不得依赖单进程后台线程承担关键任务；
- 使用持久任务队列或数据库 Outbox；
- 支持死信、人工重放和告警。

### 14.3 可观测性

至少监控：

- 机会识别数量与耗时；
- AI 调用成功率、延迟和成本；
- 自动检查拦截率；
- 人工审核通过率与耗时；
- 待员工确认积压；
- 企微发送成功/未知/失败率；
- 小程序打开和事件回流率；
- 预约、到店、支付漏斗；
- DNC和投诉；
- 归因任务失败和重算次数。

---

## 15. 页面清单

### 15.1 老板端

1. 机会池：客户、类型、价值、评分原因、状态；
2. 内容审核中心：草稿预览、风险、版本、批准/驳回；
3. 企微执行看板：待确认、已发送、失败、客户响应；
4. 实验与增量归因：实验组/对照组、漏斗、收入；
5. 审计时间线：每条机会的完整证据链；
6. 配置：规则、频控、模板、模型、企微账号、门店产能。

### 15.2 员工端

1. 今日待发送；
2. 内容只读预览；
3. 打开企微/复制已审核内容；
4. 确认已发送或失败；
5. 记录客户回复；
6. 发起预约或转人工。

---

## 16. 一次性开发的内部检查顺序

### 阶段 A：现状审计与模型落地（3–5天）

- 阅读一期 models、services、API 和测试；
- 输出复用/修改/新增清单；
- 添加数据库迁移；
- 不删除现有字段和用户数据；
- 建立 Opportunity、Identity、Content Version 和 InteractionSession。
- 导入前端实际 OpenAPI，生成接口验收与字段映射报告；
- 验证关键业务事件可通过Webhook实时到达，并可通过增量API补偿。

验收：迁移可升级和回滚；一期测试全部通过。

附加验收：患者、预约、到店、订单、支付、退款、套餐和回访不再重复建设数据录入页面；RevOS以既有诊所SaaS为业务事实主系统。

### 阶段 B：Opportunity 与实验分组（4–6天）

- 沉睡客户规则识别；
- 去重、频控、产能和排除；
- 评分及 reason_codes；
- Treatment/Holdout 分组；
- 机会池页面。

验收：同一客户不会产生重复活动机会；对照组不会进入内容生成。

### 阶段 C：内容生成与审核（5–8天）

- 接文本/图片生成 API；
- 统一 Provider；
- 结构化校验和模板兜底；
- 自动风险检查；
- 内容版本和哈希；
- 人工审核页面。

验收：未经审核无法创建发送任务；修改后旧审批失效。

### 阶段 D：企微人工确认执行（5–10天）

- 先完成真实企微技术验证；
- external_userid 映射；
- 创建成员确认任务；
- 发送状态和错误映射；
- 员工任务页；
- 幂等及频控。

验收：真实客户收到经过批准的内容；无法重复发送同一 Touch。

### 阶段 E：小程序回流（5–8天）

- ticket 和 InteractionSession；
- 短期会话认证；
- 专属内容获取；
- 行为上报；
- 预约回流。

验收：修改 ticket 无法查看他人内容；重复事件不重复入库。

### 阶段 F：Outcome 与归因（5–8天）

- 到店和支付同步；
- Outcome 统一化；
- Treatment/Holdout 指标；
- 可追溯页面；
- KPI 看板。

验收：抽取任意一笔归因收入可以查看完整证据链。

---

## 17. 测试清单

### 17.1 单元测试

- 机会规则、评分和去重；
- DNC、投诉、Consent、频控；
- 实验分组；
- JSON Schema；
- 风险规则；
- 内容哈希；
- ticket 签发、过期、撤销和越权；
- 归因公式。

### 17.2 集成测试

- 机会→内容→审核→任务；
- 审核后篡改内容必须失败；
- 对照组不得触达；
- 企微 token 失效刷新；
- 不确定发送状态不得重复发送；
- 小程序事件幂等；
- 预约、到店、支付回流；
- 多租户数据隔离。

### 17.3 必须通过的安全用例

- 门店 A 无法读取门店 B 客户；
- 普通员工无法批准高风险内容；
- 小程序内不存在长期 API Key；
- ticket 篡改、过期、复制和跨客户访问被拒绝；
- 客户变更手机号后历史链不丢失；
- DNC 客户即使已有批准内容也无法发送；
- 同一个发送请求重复提交只产生一次 Touch。

### 17.4 真实门店验收

- 至少100名合格客户样本；
- 有明确对照组；
- 内容100%经过人工审核；
- 0条已知DNC违规触达；
- 发送状态可追踪；
- 至少完成一次真实预约、到店和收入回流；
- 运营人员能解释实验口径和归因结果。

---

## 18. 给 DeepSeek 的开发规则

将以下规则放在每个开发任务开头：

```text
你正在维护现有 ClinicOS 项目，请先阅读现有代码、迁移、测试和目录结构，再修改代码。

必须遵守：
1. 不重写现有系统，不删除现有功能和数据。
2. 使用现有 FastAPI、SQLAlchemy 2、Pydantic v2、Vue 3 技术栈。
3. 所有数据库变更使用 Alembic 迁移。
4. 所有业务表必须正确执行 organization_id/store_id 隔离。
5. 不信任客户端传入的租户、客户、支付结果和审核状态。
6. 未审核内容绝对不能进入发送流程。
7. 已审核内容修改后必须重新审核。
8. 对照组不得生成真实触达。
9. DNC、投诉、未授权和频控必须在发送前再次校验。
10. 所有外部调用必须有超时、错误映射、幂等和安全日志。
11. 不在代码、前端、小程序或日志中暴露密钥和敏感个人信息。
12. 每完成一个功能同时补充单元测试、集成测试和必要文档。
13. 不自行增加本任务之外的模块，不引入复杂 Agent 框架。
14. 先输出变更计划和涉及文件，确认现有实现后再编码。
15. 完成后报告：修改文件、迁移、接口、测试结果、遗留风险。
```

### 18.1 推荐逐任务投喂顺序

不要把整份二期一次性交给 DeepSeek 直接生成全部代码。按以下顺序逐项开发：

1. 审计一期代码并输出差距报告；
2. CustomerIdentity 和 Opportunity 模型与迁移；
3. 沉睡召回识别与去重；
4. 实验分组和对照组保护；
5. ContentDraft/Review 版本模型；
6. 内容 Provider 接口和一个实际供应商；
7. 自动检查；
8. 人工审核 API 和页面；
9. SendTask/Touch 状态机；
10. 企微最小真实联调；
11. 员工确认发送页面；
12. InteractionSession 与小程序认证；
13. 行为回流；
14. Outcome 和归因；
15. 全链路安全、隔离和回归测试。

每一步必须在测试通过后再进入下一步。

---

## 19. 最终交付物

- 数据库迁移和更新后的数据字典；
- Opportunity Engine V1；
- 内容生成 Provider 和模板兜底；
- 自动检查与人工审核中心；
- 企微人工确认执行 Gateway；
- 员工发送任务页；
- 小程序安全会话与事件回流 API；
- Outcome 与增量归因；
- 审计证据链；
- OpenAPI 文档；
- 单元、集成、安全和真实门店验收报告；
- 运维、密钥、监控、故障处理和回滚手册。

---

## 20. 产品终局边界

本期交付的核心不是“能生成一张图片”或“能发一条企微消息”，而是建立一条可靠、受控、可验证、可复用的经营执行链：

```text
Customer
→ Opportunity
→ Human-approved Action
→ Touch
→ Customer Response
→ Outcome
→ Incremental Revenue
```

完成这条链后，再将沉睡召回工作流复制到复诊超期、疗程中断、No-show 和会员到期，而不是为每个场景建设新的 Agent 或新系统。

---

## 21. 本闭环的学习数据要求

企微闭环不仅要完成发送，还必须为 RevOS 学习系统生产可用数据。

### 21.1 执行前冻结

在内容生成前保存：

- `context_snapshot_id`；
- customer value state；
- opportunity score及分项；
- reason_codes；
- detector/scoring/decision/workflow版本；
- experiment及group；
- 候选策略和最终选择。

### 21.2 内容与审核版本

保存：

- 生成供应商、模型和参数；
- Prompt模板和版本；
- 内容策略；
- 文案、图片和小程序配置版本；
- 自动规则结果；
- 审核人、决策、修改及耗时；
- 审核前后内容哈希。

不得只保留最后通过的内容。

### 21.3 实际动作

系统必须区分“建议发送”和“实际发送”，实际动作保存：

- 执行员工；
- 实际时间；
- 渠道账号；
- 最终内容版本；
- 发送和回执状态；
- 成本；
- 失败原因；
- 是否偏离系统建议。

### 21.4 结果窗口

按预先定义的观察窗口收集：

- 回复、拒绝、DNC、投诉；
- 小程序打开、点击和表单；
- 预约、改期、取消、No-show；
- 到店；
- 订单、支付和退款。

支付结果只能来自可信服务端或业务系统同步。

### 21.5 策略效果

该闭环结束后写入 `strategy_performance`，至少包括：

- eligible/sample size；
- treatment/control结果；
- 回复、预约、到店和支付率；
- DNC和投诉率；
- 增量收入、增量毛利、总成本和ROI；
- 置信区间/方向性结论；
- 数据完整性与可信等级。

### 21.6 本期自动化边界

本期系统可以自动：

- 汇总策略表现；
- 发现优于或劣于基线的版本；
- 生成策略调整建议；
- 推荐进入影子或小流量实验。

本期系统不可以自动：

- 修改合规规则；
- 全量切换新策略；
- 提高触达频率；
- 创建未经批准的优惠；
- 因短期点击率高而自动推广内容；
- 绕过人工审核或员工确认。

策略升级必须通过“建议 → 人工批准 → 影子运行 → 小流量实验 → 放量 → 可回滚”。
