"""营销内容合规：风险规则扫描 + 人工审批 + 发布留痕（规格 10.3 / 13）。"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.ids import new_id
from ..core.timeutil import utcnow
from ..models import ContentReview

# 风险规则：命中即标记（MVP 规则库，正式商用需法律审查）
RISK_RULES = [
    {"rule": "绝对化疗效承诺", "pattern": r"根治|治愈|包好|永不复发|百分百|100%|特效|神效|立竿见影|一针见效|断根", "severity": "high"},
    {"rule": "医疗广告违禁词", "pattern": r"最先进|第一|顶级|国家级|世界级|独家秘方|祖传秘方", "severity": "high"},
    {"rule": "诱导就医/夸大", "pattern": r"免费治疗|免费检查|不治退费|无效退款|保证有效", "severity": "medium"},
    {"rule": "个人案例佐证", "pattern": r"患者反馈|某某患者|治好案例|痊愈案例|亲身体验", "severity": "medium"},
    {"rule": "价格促销敏感", "pattern": r"秒杀|限时抢购|仅此一天|最后一天|吐血价", "severity": "low"},
    {"rule": "个人信息索取", "pattern": r"身份证|银行卡|验证码|密码", "severity": "high"},
    {"rule": "绝对禁止人群", "pattern": r"孕妇|儿童|老人", "severity": "low"},  # 需按产品谨慎，占位提示
]


def scan_content(text: str) -> dict:
    """风险扫描：返回命中的规则与风险分。"""
    flags = []
    score = 0.0
    for rule in RISK_RULES:
        for m in re.finditer(rule["pattern"], text):
            flags.append({"rule": rule["rule"], "matched": m.group(0),
                          "severity": rule["severity"], "position": m.start()})
            score += {"high": 3.0, "medium": 2.0, "low": 1.0}[rule["severity"]]
    return {"flags": flags, "risk_score": round(min(score, 10.0), 1),
            "safe": len(flags) == 0}


def create_review(db: Session, organization_id: str, store_id: str | None,
                  campaign_id: str | None, content_text: str, channel: str,
                  touch_id: str | None = None) -> ContentReview:
    scan = scan_content(content_text)
    status = "pending" if not scan["safe"] else "pending"  # 一律人工审批（规格：必要人工审批）
    review = ContentReview(
        content_review_id=new_id("content_review"),
        organization_id=organization_id, store_id=store_id,
        campaign_id=campaign_id, touch_id=touch_id,
        content_text=content_text, channel=channel,
        risk_flags=scan["flags"], risk_score=scan["risk_score"],
        status=status, approved=False,
        created_by_type="AI",
    )
    db.add(review)
    db.commit()
    return review


def approve_review(db: Session, review_id: str, reviewer: str, approved: bool, note: str | None = None) -> ContentReview:
    review = db.get(ContentReview, review_id)
    if review is None:
        return None
    review.status = "approved" if approved else "rejected"
    review.approved = approved
    review.reviewed_by = reviewer
    review.reviewed_at = utcnow()
    review.review_note = note
    db.commit()
    return review


def list_reviews(db: Session, store_id: str | None = None, status: str | None = None) -> list[ContentReview]:
    q = select(ContentReview).where(ContentReview.deleted_at.is_(None))
    if store_id:
        q = q.where(ContentReview.store_id == store_id)
    if status:
        q = q.where(ContentReview.status == status)
    return list(db.scalars(q.order_by(ContentReview.created_at.desc()).limit(100)).all())