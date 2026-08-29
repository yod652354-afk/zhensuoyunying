"""自动合规检查（规格 03 §12 / 企微规格 §7.1）。

检查顺序：结构 → 敏感信息 → 医疗广告风险词 → 绝对化/疗效/恐惧诱导 →
优惠真实性 → 虚假稀缺/统计数字 → Consent/DNC/投诉 → 14天频控 →
客户/员工当日触达上限 → 内容哈希。

blocked 风险不得通过普通审核员强制发送。
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import RiskLevel
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Patient, Task, Touch
from ...models.revos import ContentDraft, ContentReviewRecord, Opportunity

MEDICAL_AD_WORDS = [
    "治愈", "根治", "康复率", "有效率", "显效", "特效", "疗效显著", "保证痊愈",
    "无副作用", "包治百病", "药到病除",
]
ABSOLUTE_WORDS = ["最优", "最好", "最低", "最高", "第一名", "唯一", "100%", "百分百",
                  "绝对", "彻底", "永久", "史上", "顶级", "极致"]
FEAR_WORDS = ["再不治疗", "错过就", "晚了", "恶化", "致命", "危险", "后悔"]
FAKE_SCARCITY = ["仅剩", "最后", "名额", "抢购", "限量", "倒计时", "马上涨价"]
SENSITIVE_PATTERNS = [
    r"1[3-9]\d{9}",                # 手机号
    r"\d{17}[\dXx]",               # 身份证
    r"1[3-9]\d{9}|0\d{2,3}-?\d{7,8}",  # 座机
]


@dataclass
class RuleResult:
    rule: str
    passed: bool
    severity: str = "low"  # info/low/medium/high/blocked
    detail: str | None = None


def run_machine_check(
    db: Session,
    draft: ContentDraft,
    opportunity: Opportunity | None = None,
    execution_plan_id: str | None = None,
    causation_event_id: str | None = None,
) -> ContentReviewRecord:
    """对内容草稿执行 10 项自动检查，产出机器审核记录。"""
    from ...events.bus import emit
    from ...core.enums import ActorType, ReviewDecision, ReviewType

    settings = get_settings()
    text = draft.wecom_text or ""
    results: list[RuleResult] = []
    patient = db.get(Patient, opportunity.patient_id) if opportunity and opportunity.patient_id else None

    # 1) 结构检查
    results.append(RuleResult("structure", bool(draft.title and len(text) >= 5 and len(text) <= 1000),
                              "high" if not (draft.title and len(text) >= 5) else "low",
                              "标题或正文缺失/超长" if not (draft.title and len(text) >= 5) else None))

    # 2) 敏感信息泄露
    sensitive_hits = []
    for pat in SENSITIVE_PATTERNS:
        m = re.search(pat, text)
        if m:
            sensitive_hits.append(pat)
    results.append(RuleResult("sensitive_info", not sensitive_hits, "blocked",
                              f"命中敏感信息模式: {sensitive_hits}" if sensitive_hits else None))

    # 3) 医疗广告风险词
    ad_hits = [w for w in MEDICAL_AD_WORDS if w in text]
    results.append(RuleResult("medical_ad", not ad_hits, "high", f"医疗广告词: {ad_hits}" if ad_hits else None))

    # 4) 绝对化 / 疗效承诺 / 恐惧诱导
    abs_hits = [w for w in ABSOLUTE_WORDS if w in text]
    fear_hits = [w for w in FEAR_WORDS if w in text]
    results.append(RuleResult("absolutes", not abs_hits, "high", f"绝对化用语: {abs_hits}" if abs_hits else None))
    results.append(RuleResult("fear_inducement", not fear_hits, "high", f"恐惧诱导词: {fear_hits}" if fear_hits else None))

    # 5) 优惠/价格/有效期真实性（V1：禁止未经配置的优惠数字）
    price_hits = re.findall(r"¥\s?\d+|[0-9]+\s*元|[0-9]+\s*折", text)
    results.append(RuleResult("offer_truth", not price_hits, "high",
                              f"出现未配置优惠数字: {price_hits}" if price_hits else None))

    # 6) 虚假稀缺 / 未经授权统计数字
    scarcity_hits = [w for w in FAKE_SCARCITY if w in text]
    stat_hits = re.findall(r"\d+\s*(人|名|位|例)", text)
    results.append(RuleResult("fake_scarcity", not scarcity_hits and not stat_hits, "high",
                              f"虚假稀缺/统计数字: {scarcity_hits or stat_hits}" if (scarcity_hits or stat_hits) else None))

    # 7) Consent / DNC / 投诉（发送前再次检查）
    gate_ok = True
    gate_detail = None
    if patient:
        if patient.dnc:
            gate_ok, gate_detail = False, "DNC"
        elif patient.complaint_flag:
            gate_ok, gate_detail = False, "COMPLAINT"
        elif patient.consent_status == "denied":
            gate_ok, gate_detail = False, "CONSENT_DENIED"
        elif patient.contact_status == "invalid":
            gate_ok, gate_detail = False, "INVALID_CONTACT"
    results.append(RuleResult("customer_gate", gate_ok, "blocked" if not gate_ok else "low", gate_detail))

    # 8) 14 天频控
    freq_ok = True
    if opportunity and opportunity.patient_id:
        since = utcnow() - timedelta(days=settings.revos_touch_frequency_days)
        recent = db.scalar(
            select(Touch.touch_id).where(
                Touch.patient_id == opportunity.patient_id, Touch.sent_at >= since,
                Touch.deleted_at.is_(None),
            ).limit(1)
        )
        if recent:
            freq_ok = False
    results.append(RuleResult("frequency_14d", freq_ok, "high" if not freq_ok else "low",
                              "近14天已触达" if not freq_ok else None))

    # 9) 客户/员工当日触达上限（对比配置上限，非"存在即阻断"）
    capacity_ok = True
    capacity_detail = None
    if opportunity and opportunity.patient_id:
        today = utcnow().date()
        start = datetime.combine(today, datetime.min.time())
        today_count = db.scalar(
            select(func.count()).select_from(Touch).where(
                Touch.organization_id == opportunity.organization_id,
                Touch.sent_at >= start,
                Touch.deleted_at.is_(None),
            )
        ) or 0
        if today_count >= settings.revos_store_daily_touch_limit:
            capacity_ok = False
            capacity_detail = f"门店当日触达已达上限（{today_count}/{settings.revos_store_daily_touch_limit}）"
    results.append(RuleResult("capacity_limit", capacity_ok, "high" if not capacity_ok else "low",
                              capacity_detail))

    # 10) 内容哈希
    results.append(RuleResult("content_hash", bool(draft.content_hash), "low", None))

    # 汇总风险等级
    severities = [r.severity for r in results if not r.passed]
    if "blocked" in severities:
        risk = RiskLevel.BLOCKED
    elif "high" in severities:
        risk = RiskLevel.HIGH
    elif "medium" in severities:
        risk = RiskLevel.MEDIUM
    else:
        risk = RiskLevel.LOW

    record = ContentReviewRecord(
        review_id=new_id("content_review_record"),
        organization_id=draft.organization_id,
        store_id=draft.store_id,
        content_draft_id=draft.content_draft_id,
        execution_plan_id=execution_plan_id,
        review_type=ReviewType.MACHINE,
        decision=ReviewDecision.APPROVED if risk in (RiskLevel.LOW, RiskLevel.MEDIUM) else ReviewDecision.REJECTED,
        risk_level=risk,
        rule_results=[r.__dict__ for r in results],
        content_hash=draft.content_hash,
        reviewed_at=utcnow(),
    )
    db.add(record)
    draft.risk_flags = [r.detail for r in results if not r.passed and r.detail]
    if risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
        draft.status = "pending_review"
    elif risk == RiskLevel.BLOCKED:
        draft.status = "check_failed"
    else:
        draft.status = "check_failed"
    db.flush()
    emit(db, "content.machine_checked", record.organization_id, "content_draft", draft.content_draft_id,
         store_id=record.store_id, patient_id=opportunity.patient_id if opportunity else None,
         actor_type=ActorType.AI,
         correlation_id=opportunity.opportunity_id if opportunity else None, causation_id=causation_event_id,
         payload={"risk_level": risk.value, "rule_count": len(results), "blocked": risk == RiskLevel.BLOCKED})
    return record
