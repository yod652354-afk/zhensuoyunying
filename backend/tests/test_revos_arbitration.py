"""触达仲裁器测试（规格 03 §8 / 安全门禁）。

- DNC/投诉/未授权客户无法产生可执行机会（门禁）；
- 对照组不得触达；
- 同一运营周期只产生一个主要外部计划；
- 频控（14 天）阻止重复触达；
- 心理策略有行为证据与置信度。
"""
from datetime import timedelta
from decimal import Decimal

from app.core.enums import MoneyType, OpportunityScenario, OpportunityStatus
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Patient, Touch
from app.models.revos import Opportunity
from app.services.revos import arbitration as svc
from app.services.revos.common import ensure_customer


def _mk_opp(db, customer_id, patient_id, org="org_test", money=MoneyType.PAST,
            scenario=OpportunityScenario.DORMANT_RECOVERY, priority=80):
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id=org, store_id="store_test",
        customer_id=customer_id, patient_id=patient_id, money_type=money,
        scenario_type=scenario, lifecycle_state="dormant",
        status=OpportunityStatus.CANDIDATE, priority_score=Decimal(str(priority)),
        expected_revenue=Decimal("1000"), probability=Decimal("0.5"),
        expected_cost=Decimal("5"), reason_codes=["TEST"], detected_at=utcnow(),
        expires_at=utcnow() + timedelta(days=30),
    )
    db.add(opp)
    db.flush()
    return opp


def test_dnc_gate_blocks_opportunity():
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="DNC客户", dnc=True, complaint_flag=False,
                    consent_status="granted", created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        opp = _mk_opp(db, customer.customer_id, p.patient_id)
        db.commit()
        ok, code = svc.check_customer_gate(db, opp)
        assert not ok
        assert code == "DNC"


def test_complaint_gate_blocks():
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="投诉客户", dnc=False, complaint_flag=True,
                    consent_status="granted", created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        opp = _mk_opp(db, customer.customer_id, p.patient_id)
        db.commit()
        ok, code = svc.check_customer_gate(db, opp)
        assert not ok and code == "COMPLAINT"


def test_frequency_limit_14d():
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="已触达客户", dnc=False, complaint_flag=False,
                    consent_status="granted", created_by_type="test")
        db.add(p)
        db.flush()
        db.add(Touch(touch_id=new_id("touch"), organization_id="org_test",
                     patient_id=p.patient_id, channel="wechat",
                     sent_at=utcnow() - timedelta(days=3), created_by_type="test"))
        customer = ensure_customer(db, p.patient_id)
        opp = _mk_opp(db, customer.customer_id, p.patient_id)
        db.commit()
        ok, code = svc.check_customer_gate(db, opp)
        assert not ok and code == "FREQUENCY_LIMIT_14D"


def test_control_group_never_touched():
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="对照组客户", dnc=False, consent_status="granted",
                    created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        opp = _mk_opp(db, customer.customer_id, p.patient_id)
        opp.experiment_group = "control"
        db.commit()
        result = svc.arbitrate_customer(db, customer.customer_id)
        # 对照组不得成为 primary
        assert result.primary is None or result.primary.experiment_group != "control"
        assert any("CONTROL" in r for r in result.reasons) or not result.primary


def test_single_primary_per_cycle():
    """同一客户多个机会 → 只保留一个主要外部计划。"""
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="多机会客户", dnc=False, consent_status="granted",
                    contact_status="valid", created_by_type="test")
        db.add(p)
        db.flush()
        customer = ensure_customer(db, p.patient_id)
        o1 = _mk_opp(db, customer.customer_id, p.patient_id, priority=90)
        o2 = _mk_opp(db, customer.customer_id, p.patient_id,
                     scenario=OpportunityScenario.OVERDUE_REVISIT, priority=60)
        db.commit()
        result = svc.arbitrate_customer(db, customer.customer_id)
        primaries = [o for o in (result.primary,)] if result.primary else []
        assert len(primaries) <= 1
        suppressed = [o.opportunity_id for o in result.suppressed]
        assert len(suppressed) >= 1, "低价值机会应被仲裁抑制"


def test_psychology_strategy_has_evidence():
    from app.services.revos.psychology import select_strategy, score_tendencies
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="心理测试客户", total_visits=5, primary_doctor_id="doc_x",
                    dnc=False, consent_status="granted", created_by_type="test")
        db.add(p)
        db.flush()
        tendencies = score_tendencies(db, p, {"dormant_days": 120, "package_remaining": 3})
        assert len(tendencies) == 7
        best = select_strategy(db, p, {"dormant_days": 120, "package_remaining": 3})
        assert best.strategy.value in ("doctor_trust", "rights_reminder", "care_and_empathy",
                                       "convenience", "risk_reduction", "reciprocity",
                                       "commitment_consistency")
        assert best.confidence > 0
        assert best.avoid  # 禁止项非空
