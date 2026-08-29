"""AI 内容生成 Provider（规格 03 §11 / 企微规格 §6）。

- TextGenerationProvider / ImageGenerationProvider 可替换接口；
- 只传脱敏经营特征，不发送手机号/身份证/病历/诊断等敏感信息；
- 结构化 JSON Schema 输出 + 校验；超时、有限重试、成本记录；
- 模板兜底（解析失败或供应商不可用）；
- Prompt/模型/参数/内容版本随草稿保存；
- 不生成医疗诊断、处方和疗效承诺。

供应商配置全部来自环境变量（REVOS_*），不写死密钥。
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import DraftStatus
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models.revos import ContentDraft, Opportunity
from .common import mask_name, mask_mobile

# 结构化输出 JSON Schema（服务端校验）
TEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 60},
        "wecom_text": {"type": "string", "minLength": 5, "maxLength": 1000},
        "image_prompt": {"type": "string", "maxLength": 300},
        "mini_program": {
            "type": "object",
            "properties": {
                "card_title": {"type": "string", "maxLength": 60},
                "page_code": {"type": "string"},
            },
            "required": ["card_title", "page_code"],
        },
        "strategy_code": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "wecom_text", "strategy_code", "risk_flags"],
}

CONTENT_FORBIDDEN_PATTERNS = [
    "根治", "治愈", "百分百", "100%有效", "保证有效", "包治", "立竿见影",
    "仅剩", "最后X个", "名额有限", "再不治疗", "错过就", "今天必须", "马上决定",
]


@dataclass
class TextGenerationRequest:
    scenario: str
    features: dict  # 脱敏经营特征
    strategy_code: str
    prompt_template_code: str | None = None
    prompt_template_version: str | None = None


@dataclass
class TextGenerationResult:
    title: str
    wecom_text: str
    image_prompt: str | None = None
    mini_program: dict | None = None
    strategy_code: str = ""
    risk_flags: list[str] = field(default_factory=list)
    model_provider: str = ""
    model_name: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal("0")
    raw: dict = field(default_factory=dict)


@dataclass
class ImageGenerationRequest:
    prompt: str
    style: str = "warm_professional"


@dataclass
class ImageGenerationResult:
    url: str
    provider: str = ""
    latency_ms: int = 0
    cost: Decimal = Decimal("0")


class TextGenerationProvider:
    name = "base"

    def generate_text(self, request: TextGenerationRequest) -> TextGenerationResult:
        raise NotImplementedError


class ImageGenerationProvider:
    name = "base"

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        raise NotImplementedError


# ---------- 模板兜底（不依赖外部服务） ----------
class TemplateFallbackProvider(TextGenerationProvider):
    name = "template_fallback"

    STRATEGY_COPY = {
        "doctor_trust": ("周医生一直惦记着您的恢复情况", "医生关怀"),
        "rights_reminder": ("您名下还有未使用的服务权益，随时为您保留", "权益提醒"),
        "convenience": ("现在预约可以为您优先安排方便的时间段", "便利预约"),
        "risk_reduction": ("您可以先来做个免费评估，再决定下一步", "风险降低"),
        "care_and_empathy": ("好久没见到您了，想了解一下您最近的情况", "近况关怀"),
        "reciprocity": ("老客户专属回馈，期待为您服务", "专属回馈"),
        "commitment_consistency": ("您之前定下的调理计划，我们已为您保留进度", "计划续接"),
    }

    def generate_text(self, request: TextGenerationRequest) -> TextGenerationResult:
        strategy = request.strategy_code or "care_and_empathy"
        body, title = self.STRATEGY_COPY.get(strategy, self.STRATEGY_COPY["care_and_empathy"])
        store = request.features.get("store_display_name") or "门店"
        doctor = request.features.get("doctor_display_name") or "医生"
        text = f"您好，{body}。如果您方便，可以随时回复我们或到{store}看看，{doctor}会为您安排。祝您生活愉快！"
        return TextGenerationResult(
            title=title,
            wecom_text=text,
            image_prompt=None,
            mini_program={"card_title": "查看本次关怀与可用权益", "page_code": "customer_care_offer"},
            strategy_code=strategy,
            risk_flags=[],
            model_provider=self.name,
            model_name="template-v1",
            cost=Decimal("0"),
            raw={"mode": "template"},
        )


class MockImageProvider(ImageGenerationProvider):
    name = "mock_image"

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return ImageGenerationResult(
            url="https://mock.revos.local/images/care_offer_v1.png",
            provider=self.name,
            latency_ms=5,
            cost=Decimal("0"),
        )


# ---------- 通用 HTTP JSON Provider（供应商经环境变量注入） ----------
class HttpJsonTextProvider(TextGenerationProvider):
    """调用任意 JSON 供应商（OpenAI 兼容 / 自建服务），超时 + 有限重试 + 成本记录。"""

    def __init__(self, url: str, api_key: str, model: str):
        self.name = "http_json"
        self.url = url
        self.api_key = api_key
        self.model = model

    def generate_text(self, request: TextGenerationRequest) -> TextGenerationResult:
        import httpx

        settings = get_settings()
        payload = {
            "model": self.model,
            "scenario": request.scenario,
            "strategy_code": request.strategy_code,
            "features": request.features,
            "response_schema": TEXT_OUTPUT_SCHEMA,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.monotonic()
        last_err: Exception | None = None
        for attempt in range(max(settings.revos_llm_max_retries, 1)):
            try:
                resp = httpx.post(self.url, json=payload, headers=headers,
                                  timeout=settings.revos_llm_timeout_seconds)
                resp.raise_for_status()
                latency = int((time.monotonic() - started) * 1000)
                data = resp.json()
                return TextGenerationResult(
                    title=str(data.get("title", "")),
                    wecom_text=str(data.get("wecom_text", "")),
                    image_prompt=data.get("image_prompt"),
                    mini_program=data.get("mini_program"),
                    strategy_code=str(data.get("strategy_code", request.strategy_code)),
                    risk_flags=list(data.get("risk_flags") or []),
                    model_provider=self.name,
                    model_name=self.model,
                    latency_ms=latency,
                    input_tokens=int(data.get("input_tokens") or 0),
                    output_tokens=int(data.get("output_tokens") or 0),
                    cost=Decimal(str(data.get("cost") or 0)),
                    raw=data,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < max(settings.revos_llm_max_retries, 1) - 1:
                    time.sleep(0.5 * (2 ** attempt))
        raise RuntimeError(f"文本生成供应商失败: {last_err}")


class HttpJsonImageProvider(ImageGenerationProvider):
    def __init__(self, url: str, api_key: str, model: str):
        self.name = "http_json_image"
        self.url = url
        self.api_key = api_key
        self.model = model

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        import httpx

        settings = get_settings()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.monotonic()
        resp = httpx.post(self.url, json={
            "model": self.model, "prompt": request.prompt, "style": request.style,
        }, headers=headers, timeout=settings.revos_llm_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
        return ImageGenerationResult(
            url=str(data.get("url", "")),
            provider=self.name,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost=Decimal(str(data.get("cost") or 0)),
        )


# ---------- Provider 工厂 ----------
def get_text_provider() -> TextGenerationProvider:
    settings = get_settings()
    if settings.revos_text_provider == "http" and settings.revos_text_provider_url:
        return HttpJsonTextProvider(
            settings.revos_text_provider_url, settings.revos_text_provider_api_key,
            settings.revos_text_provider_model,
        )
    # mock 与模板兜底同源：确定性、零成本
    return TemplateFallbackProvider()


def get_image_provider() -> ImageGenerationProvider:
    settings = get_settings()
    if settings.revos_image_provider == "http" and settings.revos_image_provider_url:
        return HttpJsonImageProvider(
            settings.revos_image_provider_url, settings.revos_image_provider_api_key,
            settings.revos_image_provider_model,
        )
    return MockImageProvider()


# ---------- 服务端校验 ----------
def _validate_text_output(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data.get("wecom_text"), str) or len(data["wecom_text"]) < 5:
        errors.append("wecom_text 缺失或过短")
    if not isinstance(data.get("title"), str) or not data["title"]:
        errors.append("title 缺失")
    if not isinstance(data.get("strategy_code"), str) or not data["strategy_code"]:
        errors.append("strategy_code 缺失")
    return errors


def _forbidden_hits(text: str) -> list[str]:
    hits = []
    lowered = text.lower()
    for pattern in CONTENT_FORBIDDEN_PATTERNS:
        if pattern in text or pattern.lower() in lowered:
            hits.append(pattern)
    return hits


def _content_hash(title: str, text: str, image_url: str | None, mp_config: dict | None) -> str:
    raw = json.dumps({"title": title, "text": text, "image": image_url, "mp": mp_config},
                     ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------- 业务服务 ----------
def build_desensitized_features(db: Session, opportunity: Opportunity) -> dict:
    """构造模型输入：只含脱敏经营特征（规格 6.2）。"""
    from ...models import Patient

    patient = db.get(Patient, opportunity.patient_id) if opportunity.patient_id else None
    context = opportunity.context_snapshot or {}
    dormant_days = context.get("dormant_days")
    bucket = "90-180" if dormant_days and 90 <= dormant_days < 180 else (
        "180+" if dormant_days and dormant_days >= 180 else "60-90")
    revenue = float(opportunity.expected_revenue or 0)
    value_level = "high" if revenue >= 1500 else ("mid" if revenue >= 500 else "low")
    return {
        "scenario": opportunity.scenario_type.value,
        "dormant_days_bucket": bucket,
        "historical_value_level": value_level,
        "package_remaining_bucket": str(context.get("package_remaining") or 0),
        "last_response": "replied" if context.get("last_response") else "unknown",
        "store_display_name": "门店",  # 脱敏：不暴露真实门店名
        "doctor_display_name": "医生",  # 脱敏
        "strategy": opportunity.workflow_code or "dormant_recovery",
    }


def generate_content(
    db: Session,
    opportunity: Opportunity,
    execution_plan_id: str | None = None,
    strategy_code: str | None = None,
    actor: str | None = None,
    causation_event_id: str | None = None,
) -> ContentDraft:
    """生成内容草稿（Provider 可替换；失败走模板兜底；成本记录）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    features = build_desensitized_features(db, opportunity)
    strategy = strategy_code or opportunity.workflow_code or "care_and_empathy"
    request = TextGenerationRequest(
        scenario=opportunity.scenario_type.value,
        features=features,
        strategy_code=strategy,
        prompt_template_code=f"dormant_recovery_{strategy}",
        prompt_template_version="v1",
    )
    provider = get_text_provider()
    result: TextGenerationResult | None = None
    fallback_used = False
    try:
        result = provider.generate_text(request)
        errors = _validate_text_output({
            "wecom_text": result.wecom_text, "title": result.title,
            "strategy_code": result.strategy_code,
        })
        if errors:
            raise ValueError("; ".join(errors))
        hits = _forbidden_hits(result.wecom_text)
        if hits:
            result.risk_flags = list(result.risk_flags) + [f"FORBIDDEN_PATTERN:{h}" for h in hits]
    except Exception:  # noqa: BLE001  供应商失败 → 模板兜底
        fallback_used = True
        result = TemplateFallbackProvider().generate_text(request)

    image_url = None
    if result.image_prompt:
        try:
            image = get_image_provider().generate_image(ImageGenerationRequest(prompt=result.image_prompt))
            image_url = image.url
        except Exception:  # noqa: BLE001  图片失败不阻断文案
            image_url = None

    mp_config = result.mini_program or {"card_title": "查看本次关怀与可用权益", "page_code": "customer_care_offer"}
    draft = ContentDraft(
        content_draft_id=new_id("content_draft"),
        organization_id=opportunity.organization_id,
        store_id=opportunity.store_id,
        opportunity_id=opportunity.opportunity_id,
        execution_plan_id=execution_plan_id,
        version=1,
        generation_mode="template" if fallback_used else ("mock" if provider.name == "template_fallback" else "ai"),
        model_provider=result.model_provider,
        model_name=result.model_name,
        prompt_template_code=request.prompt_template_code,
        prompt_template_version=request.prompt_template_version,
        strategy_code=result.strategy_code,
        input_snapshot=features,
        title=result.title,
        wecom_text=result.wecom_text,
        image_url=image_url,
        mini_program_config=mp_config,
        risk_flags=result.risk_flags,
        generation_latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost=result.cost,
        status=DraftStatus.DRAFT,
    )
    draft.content_hash = _content_hash(draft.title, draft.wecom_text, draft.image_url, draft.mini_program_config)
    db.add(draft)
    db.flush()
    emit(db, "content.generated", draft.organization_id, "content_draft", draft.content_draft_id,
         store_id=draft.store_id, patient_id=opportunity.patient_id, actor_type=ActorType.AI, actor_id=actor,
         correlation_id=opportunity.opportunity_id, causation_id=causation_event_id,
         payload={"mode": draft.generation_mode, "provider": draft.model_provider,
                  "strategy_code": draft.strategy_code, "risk_flags": draft.risk_flags,
                  "cost": float(draft.estimated_cost), "fallback": fallback_used})
    return draft
