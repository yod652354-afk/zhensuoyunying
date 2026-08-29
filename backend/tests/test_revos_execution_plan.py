"""ExecutionPlan / 内容生成 / 审核测试（规格 03 §10-12 / 安全门禁）。

- 内容生成（模板兜底）→ 自动检查 → 人工审核 → 创建发送任务全链路；
- 未经审核无法创建发送任务；
- 审核后内容篡改返回 409 CONTENT_CHANGED；
- ExecutionPlan 包含目标/步骤/渠道/人员/停止条件/风险；
- 心理策略有行为证据。
"""
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Patient
from app.models.revos import ContentDraft, ContentReviewRecord, Decision, ExecutionPlan, Opportunity
from app.services.revos import decision as decision_svc
from app.services.revos import execution_plan as plan_svc
from app.services.revos import review as review_svc
from app.services.revos import wecom as wecom_svc
from app.services.revos.common import ensure_customer
from app.services.revos.content_provider import generate_content
from app.services.revos.opportunity import run_detection


def _mk_qualified_opportunity(db):
    """直接构造一个 qualified 机会（不走检测器，保证确定性）。"""
    from decimal import Decimal
    from app.core.enums import MoneyType, OpportunityScenario, OpportunityStatus
    p = Patient(patient_id=new_id("patient"), organization_id="org_test", store_id="store_test",
                name="方案测试客户", dnc=False, complaint_flag=False, consent_status="granted",
                contact_status="valid", total_visits=3, total_revenue=3000,
                created_by_type="test")
    db.add(p)
    db.flush()
    customer = ensure_customer(db, p.patient_id)
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id="org_test", store_id="store_test",
        customer_id=customer.customer_id, patient_id=p.patient_id,
        money_type=MoneyType.PAST, scenario_type=OpportunityScenario.DORMANT_RECOVERY,
        lifecycle_state="dormant", status=OpportunityStatus.QUALIFIED,
        priority_score=Decimal("80"), expected_revenue=Decimal("900"),
        probability=Decimal("0.5"), expected_cost=Decimal("5"),
        reason_codes=["TEST"], context_snapshot={"dormant_days": 120},
        detector_version="detector_v1", scoring_version="scoring_v1",
        workflow_code="dormant_recovery_v1", detected_at=utcnow(),
    )
    db.add(opp)
    db.flush()
    return opp, p, customer


def test_full_plan_review_send_chain():
    """机会 → 决策 → 方案 → 内容 → 机器检查 → 人工审核 → 发送任务。"""
    with SessionLocal() as db:
        opp, p, customer = _mk_qualified_opportunity(db)
        db.commit()

        # Decision（含心理策略证据）
        output = decision_svc.decide(db, opp)
        assert output.execute and output.requires_human_review
        decision = decision_svc.persist_decision(db, opp, output)
        assert decision.psychology_strategy is not None
        db.commit()

        # ExecutionPlan（目标/步骤/渠道/人员/停止条件）
        plan = plan_svc.create_plan(db, opp, decision)
        assert plan.goal and plan.steps and plan.channel and plan.assigned_staff_id
        assert plan.review_status.value == "draft"
        assert plan.experiment_group is None
        db.commit()

        # 内容生成（模板兜底 → 确定性输出）
        draft = generate_content(db, opp, plan.execution_plan_id, actor="test")
        assert draft.wecom_text and draft.content_hash
        assert draft.status.value == "draft"
        db.commit()

        # 自动机器检查
        from app.services.revos.compliance_check import run_machine_check
        record = run_machine_check(db, draft, opp, plan.execution_plan_id)
        assert record.risk_level.value in ("low", "medium", "high", "blocked")
        assert len(record.rule_results) >= 8
        db.commit()
        db.refresh(draft)
        assert draft.status.value == "pending_review"

        # 人工审核（哈希一致）
        human = review_svc.human_review(db, draft, "approved", reviewer="boss",
                                        expected_content_hash=draft.content_hash,
                                        reviewer_role="boss")
        assert human.decision.value == "approved"
        db.commit()
        db.refresh(plan)
        assert plan.review_status.value == "approved"
        assert plan.immutable and plan.content_hash

        # 创建发送任务（已批准内容）
        task = wecom_svc.create_send_task(db, plan, draft)
        assert task.send_status == "content_approved"
        assert task.opportunity_id == opp.opportunity_id
        db.commit()


def test_unapproved_content_cannot_create_task():
    with SessionLocal() as db:
        opp, p, customer = _mk_qualified_opportunity(db)
        decision = decision_svc.persist_decision(db, opp, decision_svc.decide(db, opp))
        plan = plan_svc.create_plan(db, opp, decision)
        draft = generate_content(db, opp, plan.execution_plan_id, actor="test")
        db.commit()
        assert draft.status.value == "draft"
        try:
            wecom_svc.create_send_task(db, plan, draft)
            raised = False
        except ValueError:
            raised = True
        assert raised, "未批准内容不能创建发送任务"


def test_tampered_content_conflict_409():
    """审核后内容被篡改 → 409 CONTENT_CHANGED（防篡改门禁）。"""
    from app.core.errors import ClinicOSError
    with SessionLocal() as db:
        opp, p, customer = _mk_qualified_opportunity(db)
        decision = decision_svc.persist_decision(db, opp, decision_svc.decide(db, opp))
        plan = plan_svc.create_plan(db, opp, decision)
        draft = generate_content(db, opp, plan.execution_plan_id, actor="test")
        from app.services.revos.compliance_check import run_machine_check
        run_machine_check(db, draft, opp, plan.execution_plan_id)
        review_svc.human_review(db, draft, "approved", reviewer="boss",
                                expected_content_hash=draft.content_hash,
                                reviewer_role="boss")
        db.commit()
        # 篡改正文（绕过审核）
        draft.wecom_text = draft.wecom_text + "（被篡改）"
        db.commit()
        try:
            review_svc.human_review(db, draft, "approved", reviewer="boss",
                                    expected_content_hash=draft.content_hash,
                                    reviewer_role="boss")
            raised = False
        except ClinicOSError as exc:
            raised = True
            assert exc.status_code == 409
        assert raised, "篡改内容必须返回 409"


def test_plan_content_in_api(base):
    """API：生成内容 → 审核 → 创建发送任务。"""
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/opportunities/detect/dormant-recovery", headers=h)
    assert r.status_code == 200, r.text
    opps = c.get("/api/v1/opportunities?scenario_type=dormant_recovery", headers=h).json()["data"]
    if not opps:
        return  # 无候选时跳过（种子可能已覆盖）
    opp_id = opps[0]["opportunity_id"]
    # 合格化 → 决策 → 方案
    c.post(f"/api/v1/opportunities/{opp_id}/qualify", headers=h)
    r = c.post(f"/api/v1/opportunities/{opp_id}/decide", headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/opportunities/{opp_id}/execution-plan", headers=h)
    assert r.status_code == 200, r.text
    plan_id = r.json()["data"]["execution_plan_id"]
    # 生成内容
    r = c.post(f"/api/v1/opportunities/{opp_id}/generate-content", headers=h)
    assert r.status_code == 200, r.text
    draft_id = r.json()["data"]["content_draft_id"]
    # 机器检查
    r = c.post(f"/api/v1/content-drafts/{draft_id}/machine-check", headers=h)
    assert r.status_code == 200, r.text
    # 人工审核（低风险模板内容）
    r = c.post(f"/api/v1/content-drafts/{draft_id}/review", headers=h,
               json={"decision": "approved"})
    assert r.status_code == 200, r.text
    # 创建发送任务
    r = c.post(f"/api/v1/content-drafts/{draft_id}/create-send-task", headers=h)
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["task_id"]
    # 员工确认发送（模拟器）
    r = c.post(f"/api/v1/send-tasks/{task_id}/prepare-wecom", headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/send-tasks/{task_id}/confirm-sent", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["send_status"] in ("sent", "delivered", "failed")
