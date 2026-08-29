"""R-04 重复归因测试（防广播）。

- 一个客户三个机会，一笔支付只产生一个 primary attribution；
- 非主机会不得重复 WON；
- 归因窗口外支付不匹配；
- Touch 发生前的支付不匹配；
- 退款能找到原支付与 primary attribution；
- 无法匹配进入人工队列。
"""
from datetime import timedelta
from decimal import Decimal

from app.core.enums import MatchStatus, OpportunityStatus
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Patient
from app.models.business import BusinessFact, OpportunityOutcomeLink
from app.models.revos import Customer, ExecutionPlan, Opportunity
from app.services.revos import outcome as svc_outcome
from app.services.revos.common import ensure_customer
from app.services.revos.fact_matching import match_fact, record_fact


def _mk_opp(db, customer, scenario="dormant_recovery", status=OpportunityStatus.EXECUTING,
            detected_days_ago=3, plan=True, money="past"):
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id="org_test", store_id="store_test",
        customer_id=customer.customer_id, patient_id=customer.patient_id,
        money_type=money, scenario_type=scenario, lifecycle_state="dormant",
        status=status, priority_score=Decimal("70"),
        expected_revenue=Decimal("1000"), probability=Decimal("0.5"),
        expected_cost=Decimal("5"), reason_codes=["TEST"],
        detector_version="detector_v1", workflow_code=f"{scenario}_v1",
        detected_at=utcnow() - timedelta(days=detected_days_ago),
        expires_at=utcnow() + timedelta(days=30),
    )
    db.add(opp)
    db.flush()
    if plan:
        db.add(ExecutionPlan(
            execution_plan_id=new_id("execution_plan"), organization_id="org_test",
            store_id="store_test", opportunity_id=opp.opportunity_id,
            customer_id=customer.customer_id, patient_id=customer.patient_id,
            plan_version=1, goal="测试方案", steps=[], channel="enterprise_wechat",
            review_status="approved", review_decision="approved",
            expected_value=Decimal("500"), expected_cost=Decimal("5"),
            status="executing", immutable=True,
        ))
    return opp


def test_one_payment_one_primary():
    """一个客户三个机会，一笔支付只产生一个 primary。"""
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="防广播客户", dnc=False, consent_status="granted",
                    created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        scenarios = ["dormant_recovery", "overdue_revisit", "followup_care"]
        opps = [_mk_opp(db, customer, scenario=s) for s in scenarios]
        db.commit()
        results = svc_outcome.sync_from_trusted_event(
            db, "payment.completed", p.patient_id,
            occurred_at=utcnow(), revenue=1000, event_id="evt-single-pay")
        db.commit()
        # 只有一个 primary 关联
        facts = db.query(BusinessFact).filter(BusinessFact.source_event_id == "evt-single-pay").all()
        assert len(facts) == 1
        primaries = db.query(OpportunityOutcomeLink).filter(
            OpportunityOutcomeLink.fact_id == facts[0].fact_id,
            OpportunityOutcomeLink.link_type == "primary",
        ).all()
        assert len(primaries) == 1, "同事实只允许一个 primary"
        # 只有 primary 机会 WON
        won = [o for o in db.query(Opportunity).filter(Opportunity.patient_id == p.patient_id).all()
               if o.status == OpportunityStatus.WON]
        assert len(won) == 1


def test_outside_window_not_matched():
    """归因窗口外支付不匹配。"""
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="窗口外客户", dnc=False, consent_status="granted",
                    created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        _mk_opp(db, customer, detected_days_ago=60)  # 60 天前检测
        db.commit()
        fact, _ = record_fact(
            db, "org_test", "payment", "clinicos_saas", "evt-outside",
            occurred_at=utcnow() - timedelta(days=1),
            customer_id=customer.customer_id, patient_id=p.patient_id,
            revenue_amount=1000,
        )
        match_fact(db, fact)
        db.commit()
        assert fact.match_status != MatchStatus.MATCHED


def test_manual_review_queue_without_evidence():
    """有候选但无执行证据 → 进入人工归因队列（不自动广播）。"""
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="人工归因客户", dnc=False, consent_status="granted",
                    created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        _mk_opp(db, customer, plan=False)  # 无执行方案/无 Touch
        db.commit()
        fact, _ = record_fact(
            db, "org_test", "payment", "clinicos_saas", "evt-manual",
            occurred_at=utcnow(), customer_id=customer.customer_id,
            patient_id=p.patient_id, revenue_amount=1000,
        )
        match_fact(db, fact)
        db.commit()
        assert fact.match_status == MatchStatus.MANUAL_REVIEW


def test_refund_links_to_original():
    """退款能找到原支付及 primary attribution。"""
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="退款客户", dnc=False, consent_status="granted",
                    created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        _mk_opp(db, customer)
        db.commit()
        pay = svc_outcome.sync_from_trusted_event(
            db, "payment.completed", p.patient_id,
            occurred_at=utcnow(), revenue=1000, event_id="evt-pay-r")
        db.commit()
        pay_fact = db.query(BusinessFact).filter(BusinessFact.source_event_id == "evt-pay-r").first()
        assert pay_fact.matched_opportunity_id, "支付必须匹配到 primary 机会"
        # 退款（同客户同事实层）
        refund = svc_outcome.sync_from_trusted_event(
            db, "refund.completed", p.patient_id,
            occurred_at=utcnow() + timedelta(hours=1), revenue=500, event_id="evt-ref-r")
        db.commit()
        ref_fact = db.query(BusinessFact).filter(BusinessFact.source_event_id == "evt-ref-r").first()
        # 退款与支付同属一个客户，匹配到同一机会（主方案）
        assert ref_fact.matched_opportunity_id == pay_fact.matched_opportunity_id
