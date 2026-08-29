"""稳定全局唯一 ID：前缀 + uuid hex。
对应需求规格 3.1：核心实体使用稳定全局唯一ID，禁止用姓名/手机号作为主键。
"""
import uuid

# 各实体 ID 前缀（对照规格 §4 实体）
PREFIX = {
    "organization": "org",
    "store": "store",
    "patient": "pat",
    "lead_source": "src",
    "doctor": "doc",
    "staff": "staff",
    "service": "svc",
    "appointment": "appt",
    "visit": "visit",
    "treatment_plan": "plan",
    "care_recommendation": "rec",
    "order": "ord",
    "order_item": "oi",
    "payment": "pay",
    "refund": "rfd",
    "package": "pkg",
    "package_usage": "pkguse",
    "followup": "fu",
    "campaign": "cmp",
    "campaign_audience": "ca",
    "touch": "touch",
    "feedback": "fb",
    "task": "task",
    "capacity": "cap",
    "experiment": "exp",
    "experiment_assignment": "expasg",
    "attribution": "attr",
    "event": "evt",
    "webhook_subscription": "wsub",
    "webhook_delivery": "wdel",
    # RevOS 领域（升级）
    "customer": "cus",
    "identity": "cid",
    "state": "cst",
    "opportunity": "opp",
    "decision": "dec",
    "execution_plan": "plan",
    "action": "act",
    "outcome": "out",
    "content_draft": "cd",
    "content_review_record": "crr",
    "interaction_session": "int",
    "workflow_definition": "wfd",
    "workflow_instance": "wfi",
    "strategy_version": "sv",
    "strategy_performance": "sp",
    "context_snapshot": "cs",
    "mp_event": "mpe",
}


def new_id(entity: str) -> str:
    """生成形如 pat_xxxxxxxx 的稳定唯一 ID。"""
    prefix = PREFIX.get(entity, entity)
    return f"{prefix}_{uuid.uuid4().hex}"