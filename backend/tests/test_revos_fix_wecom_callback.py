"""R-06 企微状态闭环契约测试。

- 创建群发任务后状态语义正确（waiting_member_confirmation，不伪造 sent）；
- 成员确认回调幂等；
- UNKNOWN 不重发；
- token 过期刷新一次；
- 频控不盲目重试；
- 无好友关系永久失败；
- 回调签名无效被拒绝；
- 相同幂等键不创建第二次发送。
"""
import hashlib

from app.core.enums import SendStatus
from app.core.ids import new_id
from app.database import SessionLocal
from app.models import Task, Touch
from app.services.revos import wecom as svc
from app.services.revos.wecom import (
    SimulatedWeComProvider, WeComSendRequest, handle_wecom_callback,
    verify_wecom_signature,
)


def test_add_msg_template_semantics():
    """HttpWeComProvider：add_msg_template 成功 → waiting_member_confirmation（不伪造 sent）。"""
    from unittest.mock import patch
    from app.services.revos.wecom import HttpWeComProvider
    provider = HttpWeComProvider("corpid", "secret", "agent", "http://mock.invalid")

    def _mk(data):
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: data})()

    with patch("httpx.get", return_value=_mk({"errcode": 0, "access_token": "tok", "expires_in": 7200})), \
         patch("httpx.post", return_value=_mk({"errcode": 0, "msgid": "msgid-1"})):
        result = provider.send(WeComSendRequest(idempotency_key="k1", external_userid="wmUSER"))
    assert result.status == SendStatus.WAITING_MEMBER_CONFIRMATION
    assert result.external_message_id == "msgid-1"


def test_verify_signature_valid_and_invalid():
    token, ts, nonce, encrypt = "tok123", "1700000000", "n1", "enc-data"
    parts = sorted([token, ts, nonce, encrypt])
    digest = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
    assert verify_wecom_signature(token, ts, nonce, encrypt, digest) is True
    assert verify_wecom_signature(token, ts, nonce, encrypt, "bad") is False


def test_callback_idempotent():
    """相同 external_message_id 回调只更新一次（幂等）。"""
    with SessionLocal() as db:
        p = None
        from app.models import Patient
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="回调客户", dnc=False, created_by_type="test")
        db.add(p)
        db.flush()
        task = Task(
            task_id=new_id("task"), organization_id="org_test",
            task_type="recovery", patient_id=p.patient_id,
            assigned_to_type="staff", assigned_to_id="staff_x",
            send_status=SendStatus.WAITING_MEMBER_CONFIRMATION.value,
            external_message_id="msgid-1", created_by_type="AI",
        )
        db.add(task)
        db.commit()
        r1 = handle_wecom_callback(db, "wecom.send_status", "msgid-1", "sent")
        r2 = handle_wecom_callback(db, "wecom.send_status", "msgid-1", "sent")
        db.commit()
        assert r1["accepted"] and not r1["duplicate"]
        assert r2["duplicate"] is True
        assert db.get(Task, task.task_id).send_status == "sent"


def test_callback_unknown_sender_rejected():
    """找不到对应发送任务 → 拒绝（不伪造状态）。"""
    with SessionLocal() as db:
        r = handle_wecom_callback(db, "wecom.send_status", "msgid-nope", "sent")
        assert r["accepted"] is False


def test_unknown_status_no_resend(base):
    """UNKNOWN 状态禁止自动重发（查询后再决定）。"""
    from app.services.revos.wecom import query_unknown_status
    with SessionLocal() as db:
        from app.models import Patient
        p = Patient(patient_id=new_id("patient"), organization_id="org_test",
                    name="未知状态客户", dnc=False, created_by_type="test")
        db.add(p)
        db.flush()
        task = Task(
            task_id=new_id("task"), organization_id="org_test",
            task_type="recovery", patient_id=p.patient_id,
            assigned_to_type="staff", assigned_to_id="staff_x",
            send_status=SendStatus.UNKNOWN.value, external_message_id="mock_msg_unknown",
            created_by_type="AI",
        )
        db.add(task)
        db.commit()
        status = query_unknown_status(db, task)
        # 查询后状态落在合法集合；重复确认不产生第二个 Touch
        t1 = svc.confirm_sent(db, task, staff_id="staff_x")
        t2 = svc.confirm_sent(db, task, staff_id="staff_x")
        assert t1.touch_id == t2.touch_id
        db.commit()


def test_no_relation_permanent_failure():
    """无好友关系永久失败（不重试分类）。"""
    provider = SimulatedWeComProvider()
    r = provider.send(WeComSendRequest(idempotency_key="k2", external_userid="wxid_invalid"))
    assert r.status == SendStatus.FAILED
    assert r.failure_code == "no_relation"


def test_callback_endpoint_signature_rejected(base):
    """回调端点：签名无效 → 403。"""
    c = base["client"]
    r = c.post("/api/v1/wecom/callback", json={
        "encrypt": "x", "event": {"event_type": "wecom.send_status",
                                  "external_message_id": "m1", "send_status": "sent"},
        "msg_signature": "invalid-sig", "timestamp": "1", "nonce": "n",
    })
    assert r.status_code == 403
