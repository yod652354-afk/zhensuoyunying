"""实体注册表：一个声明 = 列表/详情读端点 + 响应模型。

对照需求规格 5.2 Read API 端点清单（P0 全部 + P1 预留）。
"""
from dataclasses import dataclass, field

from ...models import (
    Appointment, Attribution, Campaign, CampaignAudience, Capacity, CareRecommendation,
    Doctor, Event, Experiment, ExperimentAssignment, Feedback, Followup, LeadSource,
    Order, OrderItem, Organization, PackageInstance, PackageUsage, Patient, Payment,
    Refund, Service, Staff, Store, Task, Touch, TreatmentPlan, Visit,
)


@dataclass
class EntitySpec:
    route: str          # URL 段，如 patients
    model: type
    pk: str             # 主键字段名，如 patient_id
    summary: str
    filters: dict = field(default_factory=dict)  # 查询参数 -> 模型字段


ENTITIES: list[EntitySpec] = [
    EntitySpec("organizations", Organization, "organization_id", "机构列表（P0）"),
    EntitySpec("stores", Store, "store_id", "门店列表（P0）", {"organization_id": "organization_id"}),
    EntitySpec("patients", Patient, "patient_id", "患者列表/增量同步（P0）", {
        "store_id": "store_id", "status": "customer_status", "stage": "customer_stage",
        "dnc": "dnc", "primary_doctor_id": "primary_doctor_id",
    }),
    EntitySpec("lead-sources", LeadSource, "source_id", "来源记录（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "source_type": "source_type",
    }),
    EntitySpec("doctors", Doctor, "doctor_id", "医生（P0）", {"store_id": "store_id"}),
    EntitySpec("staff", Staff, "staff_id", "员工（P0）", {"store_id": "store_id"}),
    EntitySpec("services", Service, "service_id", "项目/服务（P0）", {
        "store_id": "store_id", "category": "service_category",
    }),
    EntitySpec("appointments", Appointment, "appointment_id", "预约（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "doctor_id": "doctor_id",
        "status": "status",
    }),
    EntitySpec("visits", Visit, "visit_id", "到店/就诊（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "doctor_id": "doctor_id",
        "status": "visit_status", "visit_type": "visit_type",
    }),
    EntitySpec("treatment-plans", TreatmentPlan, "treatment_plan_id", "疗程/诊后计划（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "status": "plan_status",
    }),
    EntitySpec("care-recommendations", CareRecommendation, "care_recommendation_id", "后续建议事件（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "doctor_id": "doctor_id",
    }),
    EntitySpec("orders", Order, "order_id", "订单（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "status": "order_status",
    }),
    EntitySpec("order-items", OrderItem, "order_item_id", "订单明细（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "order_id": "order_id",
    }),
    EntitySpec("payments", Payment, "payment_id", "付款（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "order_id": "order_id",
        "status": "status",
    }),
    EntitySpec("refunds", Refund, "refund_id", "退款（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "order_id": "order_id",
    }),
    EntitySpec("packages", PackageInstance, "package_instance_id", "套餐实例（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "status": "status",
    }),
    EntitySpec("package-usages", PackageUsage, "package_usage_id", "套餐核销（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "package_instance_id": "package_instance_id",
    }),
    EntitySpec("followups", Followup, "followup_id", "回访（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "staff_id": "staff_id",
        "status": "status", "reason": "reason",
    }),
    EntitySpec("campaigns", Campaign, "campaign_id", "营销活动（P0）", {
        "store_id": "store_id", "status": "status", "type": "type",
    }),
    EntitySpec("campaign-audiences", CampaignAudience, "campaign_audience_id", "活动受众（P0）", {
        "store_id": "store_id", "campaign_id": "campaign_id", "patient_id": "patient_id",
        "experiment_group": "experiment_group",
    }),
    EntitySpec("touches", Touch, "touch_id", "触达事件（P0）", {
        "store_id": "store_id", "campaign_id": "campaign_id", "patient_id": "patient_id",
        "task_id": "task_id", "followup_id": "followup_id",
    }),
    EntitySpec("tasks", Task, "task_id", "经营任务（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "assigned_to_id": "assigned_to_id",
        "status": "status", "task_type": "task_type", "review_status": "review_status",
    }),
    EntitySpec("feedback", Feedback, "feedback_id", "反馈/投诉（P1）", {
        "store_id": "store_id", "patient_id": "patient_id", "complaint_flag": "complaint_flag",
    }),
    EntitySpec("capacities", Capacity, "capacity_id", "产能（P1）", {"store_id": "store_id", "doctor_id": "doctor_id"}),
    EntitySpec("experiments", Experiment, "experiment_id", "实验（P1）", {
        "store_id": "store_id", "engine": "engine", "status": "status",
    }),
    EntitySpec("experiment-assignments", ExperimentAssignment, "experiment_assignment_id", "实验分组（P1）", {
        "store_id": "store_id", "experiment_id": "experiment_id", "patient_id": "patient_id",
    }),
    EntitySpec("attributions", Attribution, "attribution_id", "归因结果（P1）", {
        "store_id": "store_id", "campaign_id": "campaign_id", "experiment_id": "experiment_id",
    }),
    EntitySpec("events", Event, "event_id", "事件回放/补偿（P0）", {
        "store_id": "store_id", "patient_id": "patient_id", "event_type": "event_type",
    }),
]