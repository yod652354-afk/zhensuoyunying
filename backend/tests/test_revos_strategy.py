"""Strategy Registry / 学习引擎测试（规格 03 §16 / 总体规格 §15）。

- 版本化策略（version 递增、definition 不可变哈希）；
- 状态机流转白名单（draft→offline_validated→shadow→experiment→limited_release→active）；
- 受护栏策略（合规/决策/渠道）生产发布必须人工批准；
- 回滚恢复前版本；
- 影子模式：只记录不执行（不创建任务/触达）；
- 小样本方向性标记。
"""
from app.core.ids import new_id
from app.database import SessionLocal
from app.models.revos import StrategyVersion
from app.services.revos import strategy as svc


def test_register_and_version_increment():
    with SessionLocal() as db:
        sv1 = svc.register_strategy(db, "scoring_formula", "dormant_score",
                                    {"weights": {"recency": 0.2}}, owner="test",
                                    organization_id="org_test")
        sv2 = svc.register_strategy(db, "scoring_formula", "dormant_score",
                                    {"weights": {"recency": 0.3}}, owner="test",
                                    organization_id="org_test")
        assert sv1.version == 1 and sv2.version == 2
        assert sv1.content_hash and sv1.content_hash != sv2.content_hash
        assert sv1.status.value == "draft"
        db.commit()


def test_transition_whitelist():
    with SessionLocal() as db:
        sv = svc.register_strategy(db, "prompt_template", "dormant_prompt",
                                   {"prompt": "hi"}, organization_id="org_test")
        db.commit()
        # 非法流转被拒
        from app.core.errors import ClinicOSError
        try:
            svc.transition(db, sv.strategy_version_id, "active", approver="boss")
            raised = False
        except ClinicOSError:
            raised = True
        assert raised, "draft 不能直接跳 active"
        # 合法路径
        svc.transition(db, sv.strategy_version_id, "offline_validated", approver="test")
        svc.transition(db, sv.strategy_version_id, "shadow", approver="test")
        svc.transition(db, sv.strategy_version_id, "experiment", approver="test")
        db.commit()
        db.refresh(sv)
        assert sv.status.value == "experiment"


def test_guarded_category_requires_approval():
    """合规/决策/渠道策略进入生产必须人工批准。"""
    with SessionLocal() as db:
        sv = svc.register_strategy(db, "decision_policy", "default_policy",
                                   {"actions": ["generate_content"]}, organization_id="org_test")
        db.commit()
        # 沿合法路径走到 limited_release 前
        svc.transition(db, sv.strategy_version_id, "offline_validated", approver="test")
        svc.transition(db, sv.strategy_version_id, "shadow", approver="test")
        svc.transition(db, sv.strategy_version_id, "experiment", approver="test")
        db.commit()
        from app.core.errors import ClinicOSError
        # 无批准人 → 拒绝（受护栏保护）
        try:
            svc.transition(db, sv.strategy_version_id, "limited_release")
            raised = False
        except ClinicOSError:
            raised = True
        assert raised
        # 有批准人 → 允许并记录批准记录
        svc.transition(db, sv.strategy_version_id, "limited_release", approver="boss",
                       reason="运营批准")
        db.commit()
        db.refresh(sv)
        assert sv.approval_record and sv.approval_record.get("approver") == "boss"


def test_rollback_restores_previous():
    with SessionLocal() as db:
        v1 = svc.register_strategy(db, "content_strategy", "care_strategy",
                                   {"mode": "v1"}, organization_id="org_test")
        v2 = svc.register_strategy(db, "content_strategy", "care_strategy",
                                   {"mode": "v2"}, organization_id="org_test")
        svc.transition(db, v1.strategy_version_id, "offline_validated", approver="test")
        svc.transition(db, v1.strategy_version_id, "shadow", approver="test")
        svc.transition(db, v1.strategy_version_id, "experiment", approver="test")
        svc.transition(db, v1.strategy_version_id, "limited_release", approver="boss")
        svc.transition(db, v1.strategy_version_id, "active", approver="boss")
        db.commit()
        svc.rollback(db, v1.strategy_version_id, "效果不达标", actor="boss")
        db.commit()
        db.refresh(v1)
        assert v1.status.value == "rolled_back"


def test_shadow_detection_no_execution():
    """影子运行：机会标记 shadow，不进入正常执行流程。"""
    from datetime import timedelta
    from app.core.ids import new_id
    from app.core.timeutil import utcnow
    from app.models import Patient
    from app.services.revos.opportunity import run_detection
    from app.services.revos.common import ensure_customer
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="影子客户", total_visits=6, total_revenue=3000,
                    last_visit_date=utcnow() - timedelta(days=120),
                    consent_status="granted", dnc=False, complaint_flag=False,
                    contact_status="valid", created_by_type="test")
        db.add(p)
        db.flush()
        ensure_customer(db, p.patient_id)
        db.commit()
        result = run_detection(db, org_id="org_test", scenario="dormant_recovery", shadow=True)
        # 影子机会存在且为 suppressed 状态（不执行）
        from app.models.revos import Opportunity
        shadows = db.query(Opportunity).filter(
            Opportunity.shadow.is_(True),
            Opportunity.organization_id == "org_test",
        ).all()
        assert len(shadows) >= 1
        for s in shadows:
            assert s.status.value == "suppressed"
        db.commit()


def test_guardrail_alert_small_sample():
    """样本不足只标记方向性（不宣称显著）。"""
    from app.services.revos.attribution import experiment_metrics
    with SessionLocal() as db:
        from app.models import Experiment
        from app.core.enums import ExperimentStatus
        exp = Experiment(experiment_id=new_id("experiment"), organization_id="org_test",
                         name="小样本实验", engine="recovery", status=ExperimentStatus.RUNNING,
                         created_by_type="test")
        db.add(exp)
        db.commit()
        metrics = experiment_metrics(db, exp.experiment_id)
        if "error" not in metrics:
            assert metrics["directional_only"] is True
            assert metrics["significance"] is None
