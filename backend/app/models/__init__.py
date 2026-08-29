"""数据模型总入口：导入所有模型以便 Base.metadata 完整注册。"""
from ..database import Base  # noqa: F401
from .appointment import Appointment, Visit  # noqa: F401
from .capacity import Capacity  # noqa: F401
from .event import Event, WebhookDelivery, WebhookSubscription  # noqa: F401
from .experiment import Attribution, Experiment, ExperimentAssignment  # noqa: F401
from .feedback import Feedback  # noqa: F401
from .finance import (  # noqa: F401
    Order, OrderItem, PackageInstance, PackageUsage, Payment, Refund,
)
from .followup import Followup  # noqa: F401
from .idempotency import IdempotencyRecord  # noqa: F401
from .marketing import Campaign, CampaignAudience, Touch  # noqa: F401
from .org import Organization, Store  # noqa: F401
from .patient import LeadSource, Patient  # noqa: F401
from .service import Service  # noqa: F401
from .staff import Doctor, Staff  # noqa: F401
from .task import Task  # noqa: F401
from .treatment import CareRecommendation, TreatmentPlan  # noqa: F401
from .user import User  # noqa: F401
from .template import MessageTemplate  # noqa: F401
from .compliance import ContentReview, ReviewSession  # noqa: F401
from .revos import (  # noqa: F401
    ActionRecord, ContentDraft, ContentReviewRecord, ContextSnapshot, Customer,
    CustomerIdentity, CustomerStateHistory, Decision, ExecutionPlan,
    InteractionSession, MpEvent, Opportunity, Outcome, StrategyPerformance,
    StrategyVersion, WorkflowDefinition, WorkflowInstance,
)
from .business import BusinessFact, OpportunityOutcomeLink  # noqa: F401
from .outbox import Job, OutboxMessage  # noqa: F401
from .connector import (  # noqa: F401
    ConnectorConfig, ConnectorRun, ReconciliationDiff, SyncCheckpoint,
)

__all__ = [
    "Organization", "Store", "Patient", "LeadSource", "Doctor", "Staff",
    "Service", "Appointment", "Visit", "TreatmentPlan", "CareRecommendation",
    "Order", "OrderItem", "Payment", "Refund", "PackageInstance", "PackageUsage",
    "Followup", "Campaign", "CampaignAudience", "Touch", "Feedback", "Task",
    "Capacity", "Experiment", "ExperimentAssignment", "Attribution",
    "Event", "WebhookSubscription", "WebhookDelivery", "IdempotencyRecord", "User", "MessageTemplate", "ContentReview", "ReviewSession",
    "Customer", "CustomerIdentity", "CustomerStateHistory", "Opportunity",
    "ContextSnapshot", "Decision", "ExecutionPlan", "ContentDraft",
    "ContentReviewRecord", "ActionRecord", "Outcome", "InteractionSession",
    "MpEvent", "WorkflowDefinition", "WorkflowInstance", "StrategyVersion",
    "StrategyPerformance",
    "BusinessFact", "OpportunityOutcomeLink", "OutboxMessage", "Job",
    "ConnectorConfig", "ConnectorRun", "SyncCheckpoint", "ReconciliationDiff",
]
