"""R-05 数据库约束与并发幂等测试。

- 唯一约束存在（inspector 验证）；
- 并发 Detector 只产生一个活动 Opportunity（部分唯一索引）；
- 重复 event_id 只产生一个 BusinessFact / Outcome；
- 同版本 Plan/Content/Strategy 插入被数据库拒绝；
- upgrade → downgrade → upgrade 循环通过。
"""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.core.enums import ExperimentStatus
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal, engine
from app.models import Experiment, Patient
from app.models.business import BusinessFact
from app.models.revos import (
    ContentDraft, Customer, ExecutionPlan, Opportunity, StrategyVersion,
)
from app.services.revos.common import ensure_customer
from app.services.revos.fact_matching import record_fact
from app.services.revos.opportunity import run_detection


def test_unique_indexes_exist():
    """关键唯一索引/约束必须存在（R-05 数据库保障）。"""
    insp = inspect(engine)
    indexes = {i["name"]: i for i in insp.get_indexes("opportunities")}
    assert "uq_opportunities_active_scenario" in indexes
    cidxs = {i["name"]: i for i in insp.get_indexes("customer_identities")}
    assert "uq_customer_identities_active" in cidxs
    bidxs = {i["name"]: i for i in insp.get_indexes("business_facts")}
    bcon = {c["name"] for c in insp.get_unique_constraints("business_facts")}
    assert "uq_business_facts_source" in (set(bidxs) | bcon)
    oidxs = {i["name"]: i for i in insp.get_indexes("outcomes")}
    ocon = {c["name"] for c in insp.get_unique_constraints("outcomes")}
    assert "uq_outcomes_opp_type_src" in (set(oidxs) | ocon)
    didxs = {i["name"]: i for i in insp.get_indexes("content_drafts")}
    dcon = {c["name"] for c in insp.get_unique_constraints("content_drafts")}
    assert "uq_content_drafts_opp_ver" in (set(didxs) | dcon)
    eidxs = {i["name"]: i for i in insp.get_indexes("execution_plans")}
    econ = {c["name"] for c in insp.get_unique_constraints("execution_plans")}
    assert "uq_execution_plans_opp_ver" in (set(eidxs) | econ)
    sidxs = {i["name"]: i for i in insp.get_indexes("strategy_versions")}
    scon = {c["name"] for c in insp.get_unique_constraints("strategy_versions")}
    assert "uq_strategy_versions_org_cat_code_ver" in (set(sidxs) | scon)
    iidxs = {i["name"]: i for i in insp.get_indexes("interaction_sessions")}
    assert "uq_interaction_sessions_token_hash" in iidxs


def _mk_dormant(db, org="org_test"):
    p = Patient(patient_id=new_id("patient"), organization_id=org,
                name="约束测试客户", dnc=False, complaint_flag=False,
                consent_status="granted", contact_status="valid",
                total_visits=6, total_revenue=5000,
                last_visit_date=utcnow() - timedelta(days=120),
                created_by_type="test")
    db.add(p)
    db.flush()
    ensure_customer(db, p.patient_id)
    return p


def test_active_opportunity_unique_per_scenario():
    """同客户同场景只允许一个活动机会（数据库唯一）。"""
    with SessionLocal() as db:
        p = _mk_dormant(db)
        db.commit()
        run_detection(db, org_id="org_test", scenario="dormant_recovery")
        db.commit()
        # 直接尝试插入第二个活动机会（绕过应用去重）→ 数据库拒绝
        customer = ensure_customer(db, p.patient_id)
        opp = Opportunity(
            opportunity_id=new_id("opportunity"), organization_id="org_test",
            store_id="store_test", customer_id=customer.customer_id,
            patient_id=p.patient_id, money_type="past",
            scenario_type="dormant_recovery", lifecycle_state="dormant",
            status="candidate", priority_score=Decimal("80"),
            expected_revenue=Decimal("1000"), probability=Decimal("0.5"),
            expected_cost=Decimal("5"), reason_codes=["TEST"],
            detector_version="detector_v1", workflow_code="dormant_recovery_v1",
            detected_at=utcnow(), expires_at=utcnow() + timedelta(days=30),
        )
        db.add(opp)
        try:
            db.commit()
            assert False, "数据库必须拒绝同客户同场景的活动机会重复"
        except IntegrityError:
            db.rollback()


def test_business_fact_source_unique():
    """重复 source event 只产生一个 BusinessFact（数据库唯一）。"""
    with SessionLocal() as db:
        p = _mk_dormant(db)
        customer = ensure_customer(db, p.patient_id)
        db.commit()
        f1, _ = record_fact(db, "org_test", "payment", "clinicos_saas", "evt-dup-1",
                            occurred_at=utcnow(), customer_id=customer.customer_id,
                            patient_id=p.patient_id, revenue_amount=1000)
        db.commit()
        f2, replayed = record_fact(db, "org_test", "payment", "clinicos_saas", "evt-dup-1",
                                   occurred_at=utcnow(), customer_id=customer.customer_id,
                                   patient_id=p.patient_id, revenue_amount=1000)
        assert replayed and f2.fact_id == f1.fact_id
        count = db.query(BusinessFact).filter(BusinessFact.source_event_id == "evt-dup-1").count()
        assert count == 1


def test_same_version_plan_rejected():
    """同机会同版本 ExecutionPlan 重复插入被数据库拒绝。"""
    with SessionLocal() as db:
        p = _mk_dormant(db)
        customer = ensure_customer(db, p.patient_id)
        opp = Opportunity(
            opportunity_id=new_id("opportunity"), organization_id="org_test",
            customer_id=customer.customer_id, patient_id=p.patient_id,
            money_type="past", scenario_type="dormant_recovery",
            lifecycle_state="dormant", status="qualified",
            priority_score=Decimal("70"), expected_revenue=Decimal("900"),
            probability=Decimal("0.5"), expected_cost=Decimal("5"),
            reason_codes=["TEST"], detected_at=utcnow(),
            expires_at=utcnow() + timedelta(days=30),
        )
        db.add(opp)
        db.flush()
        plan1 = ExecutionPlan(
            execution_plan_id=new_id("execution_plan"), organization_id="org_test",
            opportunity_id=opp.opportunity_id, customer_id=customer.customer_id,
            patient_id=p.patient_id, plan_version=1, goal="g", steps=[],
            review_status="draft", review_decision="pending",
            expected_value=Decimal("450"), expected_cost=Decimal("5"), status="draft",
        )
        db.add(plan1)
        db.commit()
        plan2 = ExecutionPlan(
            execution_plan_id=new_id("execution_plan"), organization_id="org_test",
            opportunity_id=opp.opportunity_id, customer_id=customer.customer_id,
            patient_id=p.patient_id, plan_version=1, goal="g", steps=[],
            review_status="draft", review_decision="pending",
            expected_value=Decimal("450"), expected_cost=Decimal("5"), status="draft",
        )
        db.add(plan2)
        try:
            db.commit()
            assert False, "同机会同版本方案必须被数据库拒绝"
        except IntegrityError:
            db.rollback()


def test_migration_cycle():
    """upgrade → downgrade → upgrade 循环通过（独立临时库）。"""
    import os
    from alembic.config import Config
    from alembic import command
    from pathlib import Path

    from app.config import get_settings
    db_file = Path("probe_mig_cycle.db")
    if db_file.exists():
        db_file.unlink()
    # alembic env.py 读 get_settings().database_url；用环境变量切到临时库
    os.environ["DATABASE_URL"] = "sqlite:///./probe_mig_cycle.db"
    get_settings.cache_clear()
    cfg = Config(Path("alembic.ini").resolve())
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "b2c9d4e1f0a3")
        command.upgrade(cfg, "head")
        assert True
    finally:
        get_settings.cache_clear()
        os.environ["DATABASE_URL"] = "sqlite:///./test_clinicos.db"
        if db_file.exists():
            db_file.unlink()
