# RevOS 一次性开发代码审核报告

审核日期：2026-08-29  
源码：`D:\个人文件\下载\诊所决策系统`  
审核性质：只读代码审查与独立验证，未修改业务源码

## 结论

本次开发完成了较大规模的RevOS代码骨架，后端测试、迁移和前端构建均可运行，但尚未达到“一次性完整开发通过”的验收标准。

当前建议状态：**有条件拒绝验收，修复P0/P1问题后复审**。

## 独立验证

- 后端：101 passed，2 warnings；
- Alembic：`b2c9d4e1f0a3 (head)`；
- 前端：Vite生产构建成功；
- 报告写96项测试，实际为101项，开发报告与当前代码未同步；
- 无Git仓库。

## 阻断问题

### P0-1 对照组自然结果被丢弃，增量归因会被系统性夸大

`sync_from_trusted_event()`遇到control机会直接`continue`，因此对照组的自然预约、到店和支付不会写Outcome，也不会更新Opportunity为WON。随后`experiment_metrics()`却用Opportunity.WON计算control rate。

结果：对照组转化率倾向于恒为0，Treatment-Control被夸大，平台可能把自然回流错误算成RevOS增量贡献。

正确方式：对照组必须完整记录自然Outcome，只是不能触达、不能把自然Outcome归因给执行动作。实验指标必须使用两组同口径的可信业务结果。

### P0-2 每日调度仍绕过Opportunity、ExecutionPlan和人工审核

`run_daily_tasks()`仍直接调用旧`generate_recovery_tasks()`和`run_retention_engine()`创建Task。该路径没有统一Opportunity、仲裁、心理策略、ExecutionPlan、自动检查和人工审核。

结果：系统每天可能自动生成旧式触达任务，绕开本次升级最重要的受控执行链；还可能与新Opportunity路径产生重复任务和客户重复触达。

正确方式：每日调度只负责同步/重算Customer State、运行Detectors、Opportunity去重/过期和生成待审核ExecutionPlan；旧直接任务引擎只能作为显式兼容接口或完全受门禁控制。

### P1-1 前端内置默认API Key

前端在没有JWT时自动发送`dev-key-change-me`，上传和导入页面也存在相同回退逻辑。开发报告同时声称“密钥不进入前端”，二者矛盾。

风险：任何浏览器用户都能获得该服务端凭据；如果环境误配置或未正确切换production，可能绕过登录并使用API身份。API Key只能用于服务端到服务端调用，不应成为浏览器认证回退。

正确方式：浏览器仅使用用户登录令牌；未登录统一跳转登录。删除前端API Key存储、默认值和上传/导入回退。服务端API Key用于诊所SaaS连接器等可信服务。

### P1-2 迁移缺少数据库关系与关键唯一约束

RevOS新增migration主要创建列和普通索引，未看到ForeignKey和关键UniqueConstraint。Opportunity去重、CustomerIdentity有效身份、Outcome事件幂等、内容版本、策略版本等仅靠应用代码保证。

风险：并发、重试、后台任务或手工数据操作可产生重复Opportunity、重复Outcome、孤儿Decision/Plan/Action和同版本冲突。

至少需要数据库层约束：

- 有效CustomerIdentity的组织/类型/作用域/哈希唯一性；
- 同客户同场景同周期活动Opportunity唯一性；
- Outcome的opportunity/type/source_event组合唯一性；
- ContentDraft的opportunity/version唯一性；
- ExecutionPlan的opportunity/version唯一性；
- StrategyVersion的organization/category/code/version唯一性；
- 关键父子对象ForeignKey或等效的可验证完整性方案。

### P1-3 企微真实发送状态查询没有实现

`HttpWeComProvider.query_status()`固定返回UNKNOWN，并明确写着需要按真实回调实现。对于未知状态，系统无法判断是否已经发送，无法安全重试，也无法完成可靠送达闭环。

该项可以等待真实凭证联调，但不能在报告中描述为完整的真实Gateway能力。当前只能判定模拟器/接口骨架完成。

### P1-4 客户真实事件会同时命中所有活动机会

可信事件回流按patient_id查询所有QUALIFIED/APPROVED/EXECUTING/WON机会，并把同一个预约、到店或支付写入每一个Treatment机会。缺少执行时间、归因窗口、主ExecutionPlan、Touch和业务场景匹配。

结果：同一笔支付可能使多个机会同时WON并重复进入学习和归因链，与“同周期一个主要外部行动计划”冲突。

正确方式：Outcome可以作为客户事实保存一次；机会结果映射必须经过主Plan、归因窗口、触达时间和场景资格判断，不能对所有活动机会广播。

## 其他问题

- 后端存在大量SQLAlchemy mixin告警，main.py直接全局隐藏该告警，建议修复映射方式而不是屏蔽；
- 前端主包超过1MB，生产构建有chunk size警告，可后续代码分割；
-生产关键任务仍为单进程scheduler/worker，与一次性开发要求中的持久队列/Outbox不符；
-开发报告基于工程包V2.0，未引用V2.2共识记录机制；
-无Git仓库，无法可靠确认改动范围、审查差异和回滚代码版本。

## 已确认完成的部分

- RevOS领域模型和API骨架；
- 客户状态、机会、决策、方案、内容、审核、动作、结果和策略相关模块；
- 新Alembic head；
- 租户上下文与一批安全测试；
- 模拟企微、小程序和内容Provider；
- RevOS前端页面；
- 101项后端自动化测试；
- 前端生产构建；
- 基础追溯链和策略版本能力。

## 修复后复审门禁

1. 对照组自然Outcome完整记录，新增“对照组自然支付不触达但进入实验指标”测试；
2. 每日调度不再直接创建旧Recovery/Retention Task；
3. 前端彻底移除API Key认证回退；
4. 同一支付不能重复赢得多个冲突机会；
5. 增加关键唯一约束和并发幂等测试；
6. 明确企微UNKNOWN状态的回调/查询/人工确认闭环；
7. 生产关键任务使用持久队列/Outbox，或明确降低“完整开发”口径；
8. 初始化Git并提交当前基线；
9. 更新开发报告到当前测试数和V2.2决策；
10. 后端全部测试和前端构建继续通过。

## 验收判断

当前代码可以认定为“RevOS完整架构原型和可运行开发版”，不能认定为“已正确实现增量收入闭环、自动运营闭环和生产可用版本”。
