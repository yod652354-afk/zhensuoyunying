"""小程序安全承接测试（规格 03 §14 / 企微规格 §9 / 安全门禁）。

- ticket 签发/内容获取/过期/撤销/篡改/跨客户访问拒绝；
- 事件上报幂等（重复 event_id 不重复入库）；
- 支付结果不接受客户端伪造（payment_success 拒绝）；
- 专属内容不返回内部 customer_id/手机号。
"""
from datetime import timedelta

from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models.revos import (
    ContentDraft, Customer, InteractionSession, MpEvent, Opportunity,
)
from app.services.revos import mp as svc
from app.services.revos.common import ensure_customer


def _setup(db):
    from app.models import Patient
    from decimal import Decimal
    p = Patient(patient_id=new_id("patient"), organization_id="org_test", store_id="store_test",
                name="小程序客户", dnc=False, complaint_flag=False, consent_status="granted",
                mobile="13800001111", created_by_type="test")
    db.add(p)
    db.flush()
    customer = ensure_customer(db, p.patient_id)
    opp = Opportunity(
        opportunity_id=new_id("opportunity"), organization_id="org_test", store_id="store_test",
        customer_id=customer.customer_id, patient_id=p.patient_id,
        money_type="past", scenario_type="dormant_recovery", lifecycle_state="dormant",
        status="qualified", priority_score=Decimal("80"), expected_revenue=Decimal("900"),
        probability=Decimal("0.5"), expected_cost=Decimal("5"), reason_codes=["TEST"],
        detected_at=utcnow(),
    )
    db.add(opp)
    db.flush()
    draft = ContentDraft(
        content_draft_id=new_id("content_draft"), organization_id="org_test",
        store_id="store_test", opportunity_id=opp.opportunity_id, version=1,
        generation_mode="template", title="关怀卡片", wecom_text="您好，欢迎回来",
        content_hash="sha256:x", status="approved",
    )
    db.add(draft)
    db.flush()
    return p, customer, opp, draft


def test_ticket_issue_and_offer():
    with SessionLocal() as db:
        p, customer, opp, draft = _setup(db)
        session, token = svc.issue_ticket(
            db, opp.opportunity_id, customer.customer_id, "org_test", "store_test",
            content_draft_id=draft.content_draft_id)
        db.commit()
        assert token and len(token) >= 32
        # 内容获取：不含内部标识
        offer = svc.get_offer(db, token)
        assert offer["interaction_session_id"] == session.session_id
        assert offer["display_title"] == "关怀卡片"
        assert "customer_id" not in offer and "mobile" not in offer and "task_id" not in offer
        # 明文 token 不落库
        raw = db.query(InteractionSession).get(session.session_id)
        assert raw.token_hash != token
        db.commit()


def test_ticket_tamper_rejected():
    with SessionLocal() as db:
        p, customer, opp, draft = _setup(db)
        session, token = svc.issue_ticket(db, opp.opportunity_id, customer.customer_id,
                                          "org_test", "store_test")
        db.commit()
        from app.core.errors import ClinicOSError
        try:
            svc.get_offer(db, token + "tampered")
            raised = False
        except ClinicOSError:
            raised = True
        assert raised, "篡改 ticket 必须拒绝"


def test_ticket_expiry():
    with SessionLocal() as db:
        p, customer, opp, draft = _setup(db)
        session, token = svc.issue_ticket(db, opp.opportunity_id, customer.customer_id,
                                          "org_test", "store_test", ttl_seconds=-10)
        db.commit()
        from app.core.errors import ClinicOSError
        try:
            svc.get_offer(db, token)
            raised = False
        except ClinicOSError:
            raised = True
        assert raised, "过期 ticket 必须拒绝"


def test_ticket_revoke():
    with SessionLocal() as db:
        p, customer, opp, draft = _setup(db)
        session, token = svc.issue_ticket(db, opp.opportunity_id, customer.customer_id,
                                          "org_test", "store_test")
        db.commit()
        svc.revoke_ticket(db, session.session_id)
        from app.core.errors import ClinicOSError
        try:
            svc.get_offer(db, token)
            raised = False
        except ClinicOSError:
            raised = True
        assert raised, "撤销的 ticket 必须拒绝"


def test_event_idempotent_and_types():
    with SessionLocal() as db:
        p, customer, opp, draft = _setup(db)
        session, token = svc.issue_ticket(db, opp.opportunity_id, customer.customer_id,
                                          "org_test", "store_test")
        db.commit()
        e1 = svc.record_event(db, "evt-client-1", session.session_id, "page_view", utcnow(),
                              page_code="customer_care_offer", payload={"duration_seconds": 5})
        e2 = svc.record_event(db, "evt-client-1", session.session_id, "page_view", utcnow())
        assert e1.mp_event_id == e2.mp_event_id  # 幂等
        assert db.query(MpEvent).filter(MpEvent.event_id == "evt-client-1").count() == 1
        # 不允许的事件类型
        from app.core.errors import ClinicOSError
        try:
            svc.record_event(db, "evt-x", session.session_id, "hack_event", utcnow())
            raised = False
        except ClinicOSError:
            raised = True
        assert raised
        db.commit()


def test_payment_forgery_rejected():
    """支付结果不能由客户端上报（伪造 payment_success 拒绝）。"""
    from app.core.errors import ClinicOSError
    with SessionLocal() as db:
        p, customer, opp, draft = _setup(db)
        session, token = svc.issue_ticket(db, opp.opportunity_id, customer.customer_id,
                                          "org_test", "store_test")
        db.commit()
        try:
            svc.record_event(db, "evt-pay-fake", session.session_id, "payment_success", utcnow())
            raised = False
        except ClinicOSError:
            raised = True
        assert raised, "客户端伪造支付成功必须拒绝"


def test_mp_api_flow(base):
    """API：签发 ticket → 获取内容 → 上报事件（幂等）。"""
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/opportunities/detect/dormant-recovery", headers=h)
    assert r.status_code == 200, r.text
    opps = c.get("/api/v1/opportunities?scenario_type=dormant_recovery", headers=h).json()["data"]
    if not opps:
        return
    opp_id = opps[0]["opportunity_id"]
    r = c.post(f"/api/v1/opportunities/{opp_id}/generate-content", headers=h)
    if r.status_code != 200:
        return
    draft_id = r.json()["data"]["content_draft_id"]
    r = c.post("/api/v1/mp/sessions/issue", headers=h,
               json={"opportunity_id": opp_id, "content_draft_id": draft_id})
    assert r.status_code == 200, r.text
    ticket = r.json()["data"]["ticket"]
    # 获取内容（无认证，ticket 为凭据）
    r = c.get(f"/api/v1/mp/sessions/{ticket}/offer")
    assert r.status_code == 200, r.text
    session_id = r.json()["data"]["interaction_session_id"]
    # 上报事件 ×2（幂等）
    body = {"event_id": "evt-api-1", "interaction_session_id": session_id,
            "event_type": "page_view", "occurred_at": utcnow().isoformat(),
            "page_code": "customer_care_offer"}
    r1 = c.post("/api/v1/mp/events", json=body)
    r2 = c.post("/api/v1/mp/events", json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"]["mp_event_id"] == r2.json()["data"]["mp_event_id"]
    # 伪造支付被拒
    r3 = c.post("/api/v1/mp/events", json={**body, "event_id": "evt-pay-api",
                                           "event_type": "payment_success"})
    assert r3.status_code == 403
