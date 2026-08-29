"""需求规格 §8 关键状态枚举（全部为 str 枚举，跨 SQLite/PostgreSQL 可移植）。"""
from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


# --- 机构/门店 ---
class BusinessStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CLOSED = "closed"


class StoreType(StrEnum):
    TCM_CLINIC = "tcm_clinic"          # 中医诊所
    OUTPATIENT = "outpatient"          # 门诊部
    PHYSIOTHERAPY = "physiotherapy"    # 理疗
    OTHER = "other"


# --- 患者 ---
class CustomerStatus(StrEnum):
    ACTIVE = "active"
    SLEEPING = "sleeping"
    LOST = "lost"
    NEW = "new"
    BLOCKED = "blocked"   # 免打扰/黑名单


class CustomerStage(StrEnum):
    FIRST_VISIT = "first_visit"
    REVISIT = "revisit"
    TREATMENT = "treatment"
    COMPLETED = "completed"
    DORMANT = "dormant"


# --- 人员 ---
class PersonStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class StaffRole(StrEnum):
    ASSISTANT = "assistant"
    CUSTOMER_SERVICE = "customer_service"
    THERAPIST = "therapist"
    SALES = "sales"
    MANAGER = "manager"
    OTHER = "other"


# --- 预约/到店 ---
class AppointmentStatus(StrEnum):
    CREATED = "created"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    COMPLETED = "completed"


class VisitType(StrEnum):
    FIRST_VISIT = "first_visit"
    FOLLOWUP = "followup"
    TREATMENT = "treatment"
    REVIEW = "review"
    CONSULTATION = "consultation"
    OTHER = "other"


class VisitStatus(StrEnum):
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# --- 诊后计划/建议 ---
class TreatmentPlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class RecommendationType(StrEnum):
    REVISIT = "revisit"
    TREATMENT = "treatment"
    REVIEW = "review"
    OTHER = "other"


# --- 财务 ---
class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVERSED = "reversed"


class PaymentMethod(StrEnum):
    WECHAT = "wechat"
    ALIPAY = "alipay"
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


class PackageStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    PAUSED = "paused"


# --- 回访 ---
class FollowupReason(StrEnum):
    POST_VISIT_CARE = "post_visit_care"
    REVISIT_REMINDER = "revisit_reminder"
    NO_SHOW = "no_show"
    TREATMENT_INTERRUPTION = "treatment_interruption"
    SLEEPING_CUSTOMER = "sleeping_customer"
    PACKAGE_EXPIRY = "package_expiry"
    CAMPAIGN = "campaign"
    COMPLAINT = "complaint"
    OTHER = "other"


class FollowupChannel(StrEnum):
    PHONE = "phone"
    SMS = "sms"
    WECHAT = "wechat"
    ENTERPRISE_WECHAT = "enterprise_wechat"
    MANUAL = "manual"


class FollowupStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FollowupResult(StrEnum):
    NO_ANSWER = "no_answer"
    INVALID_CONTACT = "invalid_contact"
    REPLIED = "replied"
    NOT_INTERESTED = "not_interested"
    INTERESTED = "interested"
    APPOINTMENT_CREATED = "appointment_created"
    VISITED = "visited"
    CONVERTED = "converted"
    DO_NOT_CONTACT = "do_not_contact"


# --- 营销 ---
class CampaignType(StrEnum):
    ALWAYS_ON = "always_on"
    SEASONAL = "seasonal"
    HOLIDAY = "holiday"
    NEW_SERVICE = "new_service"
    REACTIVATION = "reactivation"


class CampaignObjective(StrEnum):
    NEW_CUSTOMER = "new_customer"
    REACTIVATION = "reactivation"
    RETENTION = "retention"
    PACKAGE_SALES = "package_sales"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class ExperimentGroup(StrEnum):
    CONTROL = "control"
    TREATMENT_A = "treatment_a"
    TREATMENT_B = "treatment_b"
    TREATMENT_C = "treatment_c"
    NONE = "none"


class TouchChannel(StrEnum):
    PHONE = "phone"
    SMS = "sms"
    WECHAT = "wechat"
    ENTERPRISE_WECHAT = "enterprise_wechat"
    OFFICIAL_ACCOUNT = "official_account"
    MANUAL = "manual"


class DeliveryStatus(StrEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


# --- 反馈 ---
class FeedbackType(StrEnum):
    REVIEW = "review"
    COMPLAINT = "complaint"
    SURVEY = "survey"


# --- 任务 ---
class TaskType(StrEnum):
    RECOVERY = "recovery"
    RETENTION = "retention"
    GROWTH = "growth"
    APPOINTMENT = "appointment"
    FOLLOWUP = "followup"
    MANAGER_REVIEW = "manager_review"
    DOCTOR_ACTION = "doctor_action"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskPriority(StrEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"


class AssignedToType(StrEnum):
    STAFF = "staff"
    DOCTOR = "doctor"
    ROLE = "role"
    AI = "AI"


class CreatedByType(StrEnum):
    SYSTEM = "system"
    AI = "AI"
    STAFF = "staff"
    DOCTOR = "doctor"


# --- 实验/归因 ---
class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AttributionSourceType(StrEnum):
    TOUCH = "touch"
    TASK = "task"
    CAMPAIGN = "campaign"
    ORGANIC = "organic"
    OTHER = "other"


class AttributionModel(StrEnum):
    LAST_TOUCH = "last_touch"
    FIRST_TOUCH = "first_touch"
    RULE_BASED = "rule_based"
    HOLDOUT = "holdout"


# --- 事件 ---
class ActorType(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    STAFF = "staff"
    AI = "AI"
    SYSTEM = "system"


# ================= RevOS 领域枚举（升级规格） =================

# --- 客户生命周期状态（03-任务 §5） ---
class LifecycleState(StrEnum):
    LEAD = "lead"
    ENGAGED = "engaged"
    BOOKED = "booked"
    VISITED = "visited"
    CONVERTED = "converted"
    IN_SERVICE = "in_service"
    ACTIVE = "active"
    AT_RISK = "at_risk"
    DORMANT = "dormant"
    LOST = "lost"
    REACTIVATED = "reactivated"


# --- 三种钱 ---
class MoneyState(StrEnum):
    FUTURE = "future"
    CURRENT = "current"
    PAST = "past"


class MoneyType(StrEnum):
    FUTURE = "future"
    CURRENT = "current"
    PAST = "past"


class ValueTier(StrEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


# --- 身份类型 ---
class IdentityType(StrEnum):
    SOURCE_CUSTOMER_ID = "source_customer_id"
    MOBILE = "mobile"
    EXTERNAL_USERID = "external_userid"
    OPENID = "openid"
    UNIONID = "unionid"


# --- Opportunity ---
class OpportunityStatus(StrEnum):
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    APPROVED = "approved"
    EXECUTING = "executing"
    WON = "won"
    LOST = "lost"
    EXPIRED = "expired"
    SUPPRESSED = "suppressed"


class OpportunityScenario(StrEnum):
    DORMANT_RECOVERY = "dormant_recovery"
    OVERDUE_REVISIT = "overdue_revisit"
    NO_SHOW = "no_show"
    TREATMENT_INTERRUPTION = "treatment_interruption"
    NEW_CUSTOMER = "new_customer"
    REFERRAL = "referral"
    PACKAGE_RENEWAL = "package_renewal"
    FOLLOWUP_CARE = "followup_care"
    OTHER = "other"


# --- 消费心理策略 ---
class PsychologyStrategy(StrEnum):
    DOCTOR_TRUST = "doctor_trust"
    RIGHTS_REMINDER = "rights_reminder"
    CONVENIENCE = "convenience"
    RISK_REDUCTION = "risk_reduction"
    CARE_AND_EMPATHY = "care_and_empathy"
    RECIPROCITY = "reciprocity"
    COMMITMENT_CONSISTENCY = "commitment_consistency"


# --- ExecutionPlan / ContentDraft 状态 ---
class PlanStatus(StrEnum):
    DRAFT = "draft"
    MACHINE_CHECKED = "machine_checked"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ABORTED = "aborted"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    CHECK_FAILED = "check_failed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReviewDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class ReviewType(StrEnum):
    MACHINE = "machine"
    HUMAN = "human"


# --- Outcome ---
class OutcomeType(StrEnum):
    REPLIED = "replied"
    INTERESTED = "interested"
    REJECTED = "rejected"
    APPOINTMENT = "appointment"
    VISITED = "visited"
    PAID = "paid"
    REFUNDED = "refunded"
    DNC = "dnc"
    COMPLAINT = "complaint"
    NO_RESPONSE = "no_response"


# --- 企微发送状态（Task/Touch send_status） ---
class SendStatus(StrEnum):
    PENDING = "pending"
    CONTENT_APPROVED = "content_approved"
    WAITING_MEMBER_CONFIRMATION = "waiting_member_confirmation"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RESPONDED = "responded"
    APPOINTMENT_CREATED = "appointment_created"
    VISITED = "visited"
    PAID = "paid"
    ATTRIBUTED = "attributed"


# --- Action ---
class ActionStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionType(StrEnum):
    GENERATE_CONTENT = "generate_content"
    MACHINE_CHECK = "machine_check"
    HUMAN_REVIEW = "human_review"
    CREATE_SEND_TASK = "create_send_task"
    MEMBER_CONFIRM = "member_confirm"
    SEND_TOUCH = "send_touch"
    RECORD_OUTCOME = "record_outcome"
    ASSIGN_PLAN = "assign_plan"
    SUPPRESS = "suppress"
    OTHER = "other"


# --- 小程序会话 ---
class SessionStatus(StrEnum):
    ISSUED = "issued"
    OPENED = "opened"
    EXPIRED = "expired"
    REVOKED = "revoked"


# --- 策略注册中心 ---
class StrategyCategory(StrEnum):
    DETECTOR_RULE = "detector_rule"
    SCORING_FORMULA = "scoring_formula"
    DECISION_POLICY = "decision_policy"
    WORKFLOW_DEFINITION = "workflow_definition"
    CONTENT_STRATEGY = "content_strategy"
    PROMPT_TEMPLATE = "prompt_template"
    MESSAGE_TEMPLATE = "message_template"
    TIMING_POLICY = "timing_policy"
    CHANNEL_POLICY = "channel_policy"
    PREDICTION_MODEL = "prediction_model"


class StrategyStatus(StrEnum):
    DRAFT = "draft"
    OFFLINE_VALIDATED = "offline_validated"
    SHADOW = "shadow"
    EXPERIMENT = "experiment"
    LIMITED_RELEASE = "limited_release"
    ACTIVE = "active"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class WorkflowInstanceStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"
    BLOCKED = "blocked"


class WorkflowDefinitionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


# --- 业务事实匹配状态（R-04） ---
class MatchStatus(StrEnum):
    UNMATCHED = "unmatched"            # 未匹配到机会
    MATCHED = "matched"                # 已匹配 primary 机会
    MANUAL_REVIEW = "manual_review"    # 无法确定，进入待人工归因
    EXCLUDED = "excluded"              # 明确不匹配（窗口外/无主计划等）


# --- Job 状态（R-07） ---
class JobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"