"""Outcome 与增量归因测试（规格 03 §15 / 企微规格 §12）。

- Outcome 统一记录（回复/预约/到店/支付/DNC/投诉）；
- 支付结果只能来自可信回流（客户端伪造拒绝）；
- Treatment/Holdout 指标：增量率/增量收入/ROI；
- 小样本方向性标记；
- 归因证据链完整可追溯（Opportunity→Plan→Review→Touch→Outcome→Payment）。
"""
from datetime import timedelta
from decimal import Decimal

from app.core.enums import ExperimentStatus, OpportunityStatus
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Experiment, Patient
from app.models.revos import (
    ContentDraft, Customer, ExecutionPlan, Opportunity, Outcome,
)
from app.services.revos import attribution as svc_attr
from app.services.revos import outcome as svc_outcome
from app.services.revos.common import ensure_customer


def _setup(db):
    from app.models import Payment
    p = Patient(patient_id=new_id("patient"), organization_id="org_test", store_id="store_test",
                name="归因客户", dnc=False, complaint_flag=False, consent_status="granted",
                created_by_type="test")
    db.add(p)
    db.flush()
    customer = ensure_customer(db, p.patient_id)
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id="org_test", store_id="store_test",
        customer_id=customer.customer_id, patient_id=p.patient_id,
        money_type="past", scenario_type="dormant_recovery", lifecycle_state="dormant",
        status=OpportunityStatus.EXECUTING, priority_score=Decimal("80"),
        expected_revenue=Decimal("1000"), probability=Decimal("0.5"),
        expected_cost=Decimal("5"), reason_codes=["TEST"],
        detected_at=utcnow() - timedelta(days=10), expires_at=utcnow() + timedelta(days=20),
    )
    db.add(opp)
    db.flush()
    plan = ExecutionPlan(
        execution_plan_id=new_id("execution_plan"), organization_id="org_test",
        store_id="store_test", opportunity_id=opp.opportunity_id,
        customer_id=customer.customer_id, patient_id=p.patient_id, plan_version=1,
        goal="归因测试", steps=[], channel="enterprise_wechat",
        review_status="approved", review_decision="approved", content_hash="sha256:plan",
        expected_value=Decimal("500"), expected_cost=Decimal("5"),
        experiment_id="", status="executing", immutable=True,
    )
    db.add(plan)
    db.flush()
    return p, customer, opp, plan


def test_outcome_record_and_status():
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        out = svc_outcome.record_outcome(db, opp.opportunity_id, "paid",
                                         source_event_id="evt-pay-1",
                                         revenue_amount=880, actor="system")
        db.commit()
        assert out.outcome_type.value == "paid"
        assert out.execution_plan_id == plan.execution_plan_id
        db.refresh(opp)
        assert opp.status.value == "won"
        # 幂等：同 source_event_id 不重复
        out2 = svc_outcome.record_outcome(db, opp.opportunity_id, "paid",
                                          source_event_id="evt-pay-1")
        assert out2.outcome_id == out.outcome_id


def test_client_cannot_record_payment():
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        try:
            svc_outcome.record_outcome(db, opp.opportunity_id, "paid",
                                       source_event_id="evt-fake", allow_client=True)
            raised = False
        except PermissionError:
            raised = True
        assert raised, "客户端不能上报支付结果"


def test_dnc_outcome_suppresses_opportunity():
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        svc_outcome.record_outcome(db, opp.opportunity_id, "dnc", source_event_id="evt-dnc-1")
        db.commit()
        db.refresh(opp)
        assert opp.status.value == "suppressed"


def test_experiment_incremental_math():
    """Treatment/Holdout：Incremental Rate = T - C；对照组不得触达。"""
    with SessionLocal() as db:
        exp = Experiment(experiment_id=new_id("experiment"), organization_id="org_test",
                         name="召回实验", engine="recovery", status=ExperimentStatus.RUNNING,
                         created_by_type="test")
        db.add(exp)
        db.flush()
        exp_id = exp.experiment_id

        # Treatment 组：2 个机会 1 个赢单（支付 1500 > 预计均值，验证增量 ≠ 全部收入）
        for i in range(2):
            p, customer, opp, plan = _setup(db)
            opp.experiment_id = exp_id
            opp.experiment_group = "treatment_a"
            if i == 0:
                svc_outcome.record_outcome(db, opp.opportunity_id, "paid",
                                           source_event_id=f"evt-t-{i}", revenue_amount=1500)
        # Control 组：2 个机会 0 个赢单（对照组只观察）
        for i in range(2):
            p, customer, opp, plan = _setup(db)
            opp.experiment_id = exp_id
            opp.experiment_group = "control"
        db.commit()

        metrics = svc_attr.experiment_metrics(db, exp_id)
        assert metrics["sample"]["treatment"] == 2
        assert metrics["sample"]["control"] == 2
        t_rate = metrics["rates"]["treatment_paid_rate"]
        c_rate = metrics["rates"]["control_paid_rate"]
        assert metrics["rates"]["incremental_rate"] == round(t_rate - c_rate, 2)
        assert t_rate == 50.0 and c_rate == 0.0
        # 小样本方向性标记（低于最低样本）
        assert metrics["directional_only"] is True
        # 增量收入 = 合格人群(2) × 增量率(50%) × 均值(1000) = 1000；Treatment 总收入 1500 ≠ 增量
        assert metrics["revenue"]["incremental_revenue"] == 1000.0
        assert metrics["revenue"]["incremental_revenue"] < metrics["revenue"]["gross_revenue_treatment"]


def test_attribution_trace_chain():
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        svc_outcome.record_outcome(db, opp.opportunity_id, "visited", source_event_id="evt-v-1")
        svc_outcome.record_outcome(db, opp.opportunity_id, "paid", source_event_id="evt-p-1",
                                   revenue_amount=880)
        db.commit()
        chain = svc_attr.attribution_trace(db, opp.opportunity_id)
        assert chain["opportunity"]["opportunity_id"] == opp.opportunity_id
        assert chain["plans"], "证据链必须含执行方案"
        assert any(o["outcome_type"] == "visited" for o in chain["outcomes"])
        assert any(o["outcome_type"] == "paid" for o in chain["outcomes"])


def test_outcomes_sync_trusted():
    """可信诊所SaaS回流：payment.completed → paid Outcome。"""
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        db.commit()
        results = svc_outcome.sync_from_trusted_event(
            db, "payment.completed", p.patient_id,
            occurred_at=utcnow(), revenue=880, event_id="evt-sync-1")
        assert len(results) >= 1
        assert results[0].outcome_type.value == "paid"
        # 重复同步幂等
        results2 = svc_outcome.sync_from_trusted_event(
            db, "payment.completed", p.patient_id, occurred_at=utcnow(),
            revenue=880, event_id="evt-sync-1")
        assert len(results2) == 0 or results2[0].outcome_id == results[0].outcome_id
        db.commit()


def test_cockpit_api(base):
    """三种钱驾驶舱 API（统一 Opportunity/Outcome 数据源）。"""
    c, h = base["client"], base["headers"]
    r = c.get("/api/v1/analytics/revos/cockpit", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "money_groups" in data and "conversion_funnel" in data
    assert set(data["money_groups"].keys()) >= {"future", "current", "past"}
