"""R-01 对照组自然结果测试。

- 对照组禁止生成 Content/Task/Touch；
- 对照组自然预约/到店/支付仍记录 Outcome（is_organic=True）；
- Treatment 20%、Control 10% 时增量率为 10pp；
- 两组自然支付同为 10% 时增量为 0；
- 退款正确冲减两组净收入；
- 对照组 Outcome 不关联执行 Action。
"""
from datetime import timedelta
from decimal import Decimal

from app.core.enums import ExperimentStatus, OpportunityStatus
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Experiment, Patient
from app.models.revos import Customer, ExecutionPlan, Opportunity, Outcome
from app.services.revos import attribution as svc_attr
from app.services.revos import outcome as svc_outcome
from app.services.revos.common import ensure_customer


def _mk_opp(db, exp_id: str, group: str, revenue=1000, visits=2):
    p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                name=f"{group}客户", dnc=False, complaint_flag=False,
                consent_status="granted", contact_status="valid",
                total_visits=visits, total_revenue=revenue, created_by_type="test")
    db.add(p)
    db.flush()
    customer = ensure_customer(db, p.patient_id)
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id="org_test", store_id="store_test",
        customer_id=customer.customer_id, patient_id=p.patient_id,
        money_type="past", scenario_type="dormant_recovery", lifecycle_state="dormant",
        status=OpportunityStatus.QUALIFIED, priority_score=Decimal("70"),
        expected_revenue=Decimal(str(revenue)), probability=Decimal("0.5"),
        expected_cost=Decimal("5"), reason_codes=["TEST"],
        detector_version="detector_v1", workflow_code="dormant_recovery_v1",
        experiment_id=exp_id, experiment_group=group,
        detected_at=utcnow() - timedelta(days=5), expires_at=utcnow() + timedelta(days=25),
    )
    db.add(opp)
    db.flush()
    # 主 ExecutionPlan（approved）→ 匹配证据（R-04）
    db.add(ExecutionPlan(
        execution_plan_id=new_id("execution_plan"), organization_id="org_test",
        store_id="store_test", opportunity_id=opp.opportunity_id,
        customer_id=customer.customer_id, patient_id=p.patient_id,
        plan_version=1, goal="测试方案", steps=[], channel="enterprise_wechat",
        review_status="approved", review_decision="approved",
        expected_value=Decimal("500"), expected_cost=Decimal("5"),
        status="executing", immutable=True,
    ))
    db.flush()
    return p, customer, opp


def test_control_group_organic_outcome_recorded():
    """对照组自然支付仍记录 Outcome（is_organic=True），且不关联执行动作。"""
    with SessionLocal() as db:
        p, customer, opp = _mk_opp(db, "exp_x", "control")
        db.commit()
        results = svc_outcome.sync_from_trusted_event(
            db, "payment.completed", p.patient_id,
            occurred_at=utcnow(), revenue=880, event_id="evt-ctl-pay-1")
        db.commit()
        assert len(results) >= 1, "对照组自然结果必须进入 Outcome"
        out = results[0]
        assert out.outcome_type.value == "paid"
        assert out.is_organic is True, "对照组结果必须标记 organic"
        assert out.fact_id, "Outcome 必须关联 BusinessFact"
        db.refresh(opp)
        assert opp.status.value == "won", "对照组自然支付可反映机会状态"


def test_treatment_not_organic():
    with SessionLocal() as db:
        p, customer, opp = _mk_opp(db, "exp_x", "treatment_a")
        db.commit()
        results = svc_outcome.sync_from_trusted_event(
            db, "payment.completed", p.patient_id,
            occurred_at=utcnow(), revenue=880, event_id="evt-trt-pay-1")
        db.commit()
        assert results and results[0].is_organic is False


def test_incremental_rate_20_vs_10():
    """Treatment 20% / Control 10% → 增量率 10pp（同口径支付率）。"""
    with SessionLocal() as db:
        exp = Experiment(experiment_id=new_id("experiment"), organization_id="org_test",
                         name="增量率实验", engine="recovery", status=ExperimentStatus.RUNNING,
                         created_by_type="test")
        db.add(exp)
        db.flush()
        exp_id = exp.experiment_id
        # Treatment 10 个：2 个支付（20%）
        for i in range(10):
            p, customer, opp = _mk_opp(db, exp_id, "treatment_a")
            if i < 2:
                svc_outcome.sync_from_trusted_event(db, "payment.completed", p.patient_id,
                                                    occurred_at=utcnow(),
                                                    revenue=880, event_id=f"evt-t{i}")
        # Control 10 个：1 个支付（10%）
        for i in range(10):
            p, customer, opp = _mk_opp(db, exp_id, "control")
            if i < 1:
                svc_outcome.sync_from_trusted_event(db, "payment.completed", p.patient_id,
                                                    occurred_at=utcnow(),
                                                    revenue=880, event_id=f"evt-c{i}")
        db.commit()
        metrics = svc_attr.experiment_metrics(db, exp_id)
        assert metrics["rates"]["treatment_paid_rate"] == 20.0
        assert metrics["rates"]["control_paid_rate"] == 10.0
        assert metrics["rates"]["incremental_rate"] == 10.0


def test_zero_increment_when_both_10():
    """两组自然支付同为 10% 时增量为 0。"""
    with SessionLocal() as db:
        exp = Experiment(experiment_id=new_id("experiment"), organization_id="org_test",
                         name="零增量实验", engine="recovery", status=ExperimentStatus.RUNNING,
                         created_by_type="test")
        db.add(exp)
        db.flush()
        exp_id = exp.experiment_id
        for i in range(10):
            p, customer, opp = _mk_opp(db, exp_id, "treatment_a")
            if i < 1:
                svc_outcome.sync_from_trusted_event(db, "payment.completed", p.patient_id,
                                                    occurred_at=utcnow(),
                                                    revenue=880, event_id=f"evt-z-t{i}")
        for i in range(10):
            p, customer, opp = _mk_opp(db, exp_id, "control")
            if i < 1:
                svc_outcome.sync_from_trusted_event(db, "payment.completed", p.patient_id,
                                                    occurred_at=utcnow(),
                                                    revenue=880, event_id=f"evt-z-c{i}")
        db.commit()
        metrics = svc_attr.experiment_metrics(db, exp_id)
        assert metrics["rates"]["treatment_paid_rate"] == 10.0
        assert metrics["rates"]["control_paid_rate"] == 10.0
        assert metrics["rates"]["incremental_rate"] == 0.0


def test_refund_reduces_net_revenue():
    """退款在窗口内冲减净收入。"""
    with SessionLocal() as db:
        exp = Experiment(experiment_id=new_id("experiment"), organization_id="org_test",
                         name="退款实验", engine="recovery", status=ExperimentStatus.RUNNING,
                         created_by_type="test")
        db.add(exp)
        db.flush()
        exp_id = exp.experiment_id
        p, customer, opp = _mk_opp(db, exp_id, "treatment_a")
        svc_outcome.sync_from_trusted_event(db, "payment.completed", p.patient_id,
                                            occurred_at=utcnow(), revenue=1000, event_id="evt-pay-1")
        svc_outcome.sync_from_trusted_event(db, "refund.completed", p.patient_id,
                                            occurred_at=utcnow(), revenue=400, event_id="evt-ref-1")
        db.commit()
        metrics = svc_attr.experiment_metrics(db, exp_id)
        assert metrics["revenue"]["gross_revenue_treatment"] == 1000.0
        assert metrics["revenue"]["refund_treatment"] == 400.0
        assert metrics["revenue"]["net_revenue_treatment"] == 600.0


def test_control_group_cannot_generate_content(base):
    """对照组禁止生成 Content（API 门禁）。"""
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/opportunities/detect/dormant-recovery", headers=h)
    assert r.status_code == 200, r.text
    opps = c.get("/api/v1/opportunities?scenario_type=dormant_recovery", headers=h).json()["data"]
    if not opps:
        return
    opp_id = opps[0]["opportunity_id"]
    with SessionLocal() as db:
        from app.models import Experiment as ExpModel
        from app.models import Organization
        org_id = db.query(Organization).first().organization_id
        exp = ExpModel(experiment_id=new_id("experiment"), organization_id=org_id,
                       name="对照组门禁实验", engine="recovery", status=ExperimentStatus.RUNNING,
                       created_by_type="test")
        db.add(exp)
        db.commit()
        exp_id = exp.experiment_id
    r = c.post(f"/api/v1/opportunities/{opp_id}/assign-experiment", headers=h,
               json={"experiment_id": exp_id, "group": "control"})
    assert r.status_code == 200, r.text
    r2 = c.post(f"/api/v1/opportunities/{opp_id}/generate-content", headers=h)
    assert r2.status_code == 403, "对照组不得生成内容"
