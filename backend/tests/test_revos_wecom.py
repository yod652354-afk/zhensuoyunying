"""企微 Gateway 契约测试（规格 03 §13 / 企微规格 §8）。

- 模拟器契约：发送返回 sent + external_message_id；幂等 key 稳定；
- 同一 Touch 重复确认不重复发送（幂等）；
- DNC 客户即使有批准内容也无法发送（发送前再次检查）；
- 不确定状态查询后不盲目重复发送；
- 失败分类（无好友关系 → 不重试）。
"""
from datetime import timedelta
from decimal import Decimal

from app.core.enums import (
    MoneyType, OpportunityScenario, OpportunityStatus, SendStatus, TaskStatus,
)
from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Patient, Task, Touch
from app.models.revos import ContentDraft, Customer, ExecutionPlan, Opportunity
from app.services.revos import wecom as svc
from app.services.revos.common import ensure_customer
from app.services.revos.content_provider import generate_content
from app.services.revos.execution_plan import create_plan, submit_for_review
from app.services.revos.wecom import (
    SimulatedWeComProvider, WeComSendRequest, confirm_sent, create_send_task,
    final_pre_send_check, get_wecom_provider,
)


def _setup(db, dnc=False, has_userid=True):
    p = Patient(patient_id=new_id("patient"), organization_id="org_test", store_id="store_test",
                name="企微客户", dnc=dnc, complaint_flag=False, consent_status="granted",
                contact_status="valid", created_by_type="test")
    db.add(p)
    db.flush()
    customer = ensure_customer(db, p.patient_id)
    if has_userid:
        from app.models.revos import CustomerIdentity
        db.add(CustomerIdentity(
            identity_id=new_id("identity"), organization_id="org_test", store_id="store_test",
            customer_id=customer.customer_id, identity_type="external_userid",
            # 唯一值：部分唯一索引 (org,type,hash,scope) 禁止跨客户重复身份
            encrypted_value=f"wmTEST{new_id('u')[:10]}",
            value_hash=f"sha256:{new_id('h')[:16]}",
            provider="wecom", app_scope="corp_test", is_primary=True,
            valid_from=utcnow()))
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id="org_test", store_id="store_test",
        customer_id=customer.customer_id, patient_id=p.patient_id,
        money_type=MoneyType.PAST, scenario_type=OpportunityScenario.DORMANT_RECOVERY,
        lifecycle_state="dormant", status=OpportunityStatus.QUALIFIED,
        priority_score=Decimal("80"), expected_revenue=Decimal("900"),
        probability=Decimal("0.5"), expected_cost=Decimal("5"),
        reason_codes=["TEST"], workflow_code="dormant_recovery_v1",
        detected_at=utcnow(),
    )
    db.add(opp)
    db.flush()
    plan = ExecutionPlan(
        execution_plan_id=new_id("execution_plan"), organization_id="org_test",
        store_id="store_test", opportunity_id=opp.opportunity_id,
        customer_id=customer.customer_id, patient_id=p.patient_id, plan_version=1,
        goal="企微测试", steps=[], assigned_staff_id="staff_x", channel="enterprise_wechat",
        review_status="approved", review_decision="approved", expected_value=Decimal("450"),
        expected_cost=Decimal("5"), status="approved", immutable=True,
    )
    db.add(plan)
    db.flush()
    return p, customer, opp, plan


def test_simulator_contract():
    """模拟器契约：sent + external_message_id；幂等 key 稳定。"""
    provider = SimulatedWeComProvider()
    r1 = provider.send(WeComSendRequest(idempotency_key="tou:a", external_userid="wmUSER1"))
    assert r1.status == SendStatus.SENT
    assert r1.external_message_id
    r2 = provider.send(WeComSendRequest(idempotency_key="tou:a", external_userid="wmUSER1"))
    assert r2.external_message_id == r1.external_message_id
    # 无好友关系 → 不重试分类
    r3 = provider.send(WeComSendRequest(idempotency_key="tou:b", external_userid="wxid_invalid"))
    assert r3.status == SendStatus.FAILED
    assert r3.failure_code == "no_relation"


def test_get_provider_default_simulator():
    assert isinstance(get_wecom_provider(), SimulatedWeComProvider)


def test_confirm_sent_idempotent():
    """同一任务重复确认只产生一次 Touch。"""
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        draft = generate_content(db, opp, plan.execution_plan_id, actor="test")
        draft.status = "approved"
        db.commit()
        task = create_send_task(db, plan, draft)
        db.commit()
        t1 = confirm_sent(db, task, staff_id="staff_x")
        n1 = db.query(Touch).filter(Touch.task_id == task.task_id).count()
        t2 = confirm_sent(db, task, staff_id="staff_x")
        n2 = db.query(Touch).filter(Touch.task_id == task.task_id).count()
        assert n1 == 1 and n2 == 1
        assert t1.touch_id == t2.touch_id
        assert t1.send_status in ("sent", "delivered", "failed", "unknown")


def test_dnc_blocks_send_even_with_approved_content():
    """DNC 客户即使有批准内容也无法发送（发送前再次检查）。"""
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db, dnc=True)
        draft = generate_content(db, opp, plan.execution_plan_id, actor="test")
        draft.status = "approved"
        db.commit()
        ok, code = final_pre_send_check(db, opp)
        assert not ok and code == "DNC"
        try:
            confirm_sent(db, create_send_task(db, plan, draft), staff_id="staff_x")
            blocked = False
        except svc.WeComError:
            blocked = True
        assert blocked, "DNC 客户发送必须被阻止"


def test_control_group_blocked():
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        opp.experiment_group = "control"
        db.commit()
        ok, code = final_pre_send_check(db, opp)
        assert not ok and code == "CONTROL_GROUP"


def test_unknown_status_queries_before_resend():
    """不确定状态：先查询，禁止直接重复发送。"""
    with SessionLocal() as db:
        p, customer, opp, plan = _setup(db)
        task = Task(
            task_id=new_id("task"), organization_id="org_test", store_id="store_test",
            task_type="recovery", patient_id=p.patient_id,
            assigned_to_type="staff", assigned_to_id="staff_x",
            opportunity_id=opp.opportunity_id, execution_plan_id=plan.execution_plan_id,
            send_status=SendStatus.UNKNOWN.value, external_message_id="mock_msg_abc",
            correlation_id=opp.opportunity_id, created_by_type="AI",
        )
        db.add(task)
        db.commit()
        status = svc.query_unknown_status(db, task)
        assert status in (SendStatus.DELIVERED, SendStatus.SENT, SendStatus.UNKNOWN)
        # 重置为 failed（不参与频控统计），验证确认发送幂等
        svc.mark_failed(db, task, "test_reset", "重置状态")
        db.commit()
        t1 = confirm_sent(db, task, staff_id="staff_x")
        t2 = confirm_sent(db, task, staff_id="staff_x")
        assert t1.touch_id == t2.touch_id
        assert db.query(Touch).filter(Touch.task_id == task.task_id).count() == 1
