"""Opportunity Engine 测试（规格 03 §7 / 企微规格 §2.3）。

- 沉睡召回识别（≥60 天未到店、非 DNC/投诉/未授权）；
- 评分与 reason_codes；
- 去重：同一客户同场景不重复；
- 抑制、过期、实验分组；
- 对照组不得生成内容。
"""
from datetime import timedelta

from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Patient
from app.models.revos import Opportunity
from app.services.revos import opportunity as svc
from app.services.revos.common import ensure_customer


def _mk_dormant(db, days=120, revenue=6000, dnc=False):
    p = Patient(
        patient_id=new_id("patient"), organization_id="org_test", store_id="store_test",
        name="沉睡客户", mobile=f"13{new_id('m')[:9]}", total_visits=8,
        total_revenue=revenue, last_visit_date=utcnow() - timedelta(days=days),
        consent_status="granted", dnc=dnc, complaint_flag=False,
        contact_status="valid", created_by_type="test",
    )
    db.add(p)
    db.flush()
    return p


def test_dormant_detection_and_reason_codes():
    with SessionLocal() as db:
        p = _mk_dormant(db)
        ensure_customer(db, p.patient_id)
        db.commit()
        result = svc.run_detection(db, store_id="store_test", org_id="org_test",
                                   scenario="dormant_recovery")
        assert result["created"] >= 1
        opp = db.query(Opportunity).filter(
            Opportunity.patient_id == p.patient_id).first()
        assert opp is not None
        assert opp.money_type.value == "past"
        assert opp.scenario_type.value == "dormant_recovery"
        assert opp.priority_score is not None and float(opp.priority_score) > 0
        assert opp.reason_codes
        assert any("DORMANT" in r for r in opp.reason_codes)
        assert opp.detector_version and opp.scoring_version


def test_dedup_same_scenario():
    with SessionLocal() as db:
        p = _mk_dormant(db)
        ensure_customer(db, p.patient_id)
        db.commit()
        r1 = svc.run_detection(db, org_id="org_test", scenario="dormant_recovery")
        r2 = svc.run_detection(db, org_id="org_test", scenario="dormant_recovery")
        assert r1["created"] >= 1
        assert r2["created"] == 0
        assert r2["duplicates"] >= 1


def test_dnc_excluded_from_detection():
    with SessionLocal() as db:
        p = _mk_dormant(db, dnc=True)
        ensure_customer(db, p.patient_id)
        db.commit()
        result = svc.run_detection(db, org_id="org_test", scenario="dormant_recovery")
        # DNC 客户不得产生机会（只统计本测试患者，避免其他测试直插数据干扰）
        dnc_opps = db.query(Opportunity).filter(Opportunity.patient_id == p.patient_id).count()
        assert dnc_opps == 0


def test_opportunity_status_flow():
    with SessionLocal() as db:
        p = _mk_dormant(db)
        ensure_customer(db, p.patient_id)
        db.commit()
        svc.run_detection(db, org_id="org_test", scenario="dormant_recovery")
        opp = db.query(Opportunity).filter(Opportunity.patient_id == p.patient_id).first()
        assert opp.status.value == "candidate"
        # 合格化
        svc.qualify_opportunity(db, opp.opportunity_id, owner_staff_id="staff_x")
        db.refresh(opp)
        assert opp.status.value == "qualified"
        # 抑制
        svc.suppress_opportunity(db, opp.opportunity_id, "测试抑制", by="tester")
        db.refresh(opp)
        assert opp.status.value == "suppressed"
        assert opp.suppressed_reason


def test_expire_opportunities():
    with SessionLocal() as db:
        p = _mk_dormant(db)
        ensure_customer(db, p.patient_id)
        db.commit()
        svc.run_detection(db, org_id="org_test", scenario="dormant_recovery")
        opp = db.query(Opportunity).filter(Opportunity.patient_id == p.patient_id).first()
        opp.expires_at = utcnow() - timedelta(days=1)
        db.commit()
        n = svc.expire_opportunities(db)
        assert n >= 1
        db.refresh(opp)
        assert opp.status.value == "expired"


def test_assign_experiment_control_group(base):
    """API：机会实验分组（对照组）→ 生成内容被拒。"""
    from app.models import Organization
    with SessionLocal() as db:
        from app.models import Experiment
        from app.core.enums import ExperimentStatus
        org_id = db.query(Organization).first().organization_id
        exp = Experiment(experiment_id=new_id("experiment"), organization_id=org_id,
                         name="沉睡召回实验", engine="recovery", status=ExperimentStatus.RUNNING,
                         created_by_type="test")
        db.add(exp)
        db.commit()
        exp_id = exp.experiment_id

    c, h = base["client"], base["headers"]
    # 通过 API 检测
    r = c.post("/api/v1/opportunities/detect/dormant-recovery", headers=h)
    assert r.status_code == 200, r.text
    opps = c.get("/api/v1/opportunities?scenario_type=dormant_recovery&status=candidate",
                 headers=h).json()["data"]
    assert opps, "应存在沉睡机会"
    opp_id = opps[0]["opportunity_id"]
    # 分组为对照组
    r2 = c.post(f"/api/v1/opportunities/{opp_id}/assign-experiment", headers=h,
                json={"experiment_id": exp_id, "group": "control"})
    assert r2.status_code == 200, r2.text
    # 对照组生成内容 → 403
    r3 = c.post(f"/api/v1/opportunities/{opp_id}/generate-content", headers=h)
    assert r3.status_code == 403
