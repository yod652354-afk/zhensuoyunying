"""种子数据：让运营后台开箱即有可展示数据（仅本地开发）。"""
import random
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .core.enums import (
    AppointmentStatus, AssignedToType, CampaignObjective, CampaignStatus, CampaignType,
    CustomerStatus, ExperimentGroup, ExperimentStatus, FollowupChannel, FollowupReason,
    FollowupResult, FollowupStatus, OrderStatus, PackageStatus, PaymentMethod,
    PaymentStatus, PersonStatus, StaffRole, TaskPriority, TaskStatus, TaskType,
    TouchChannel, VisitStatus, VisitType,
)
from .core.auth import hash_password
from .core.ids import new_id
from .core.timeutil import utcnow
from .models import (
    Appointment, Campaign, CampaignAudience, CareRecommendation, Doctor,
    Experiment, ExperimentAssignment, Followup, Order, OrderItem, Organization,
    PackageInstance, PackageUsage, Patient, Payment, Service, Staff, Store, Task,
    TreatmentPlan, User, Visit,
)
from .models.event import WebhookSubscription

SURNAMES = ["张", "李", "王", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "郭"]
GIVEN = ["伟", "芳", "娜", "敏", "静", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英",
         "霞", "平", "刚", "桂英", "文轩", "子涵", "雨欣", "浩然", "梓萱", "思远", "雅琪", "俊杰", "欣怡", "志强"]


def ensure_demo_users(db: Session) -> None:
    """幂等创建演示账号：无账号时系统会被登录墙挡住，无法进入。"""
    if db.query(User).count() > 0:
        return
    org = db.query(Organization).first()
    if org is None:
        return
    staff = db.query(Staff).first()
    users = [
        User(user_id=new_id("user"), organization_id=org.organization_id,
             store_id=staff.store_id if staff else None,
             username="boss", password_hash=hash_password("boss123"),
             name="演示老板", role="boss", created_by_type="system"),
        User(user_id=new_id("user"), organization_id=org.organization_id,
             store_id=staff.store_id if staff else None,
             username="staff", password_hash=hash_password("staff123"),
             name="演示员工", role="staff",
             staff_id=staff.staff_id if staff else None, created_by_type="system"),
    ]
    db.add_all(users)
    db.commit()
    print("[seed] 演示账号已创建: boss/boss123, staff/staff123")


def run(db: Session) -> None:
    ensure_demo_users(db)
    if db.query(Organization).count() > 0:
        return
    random.seed(42)
    now = utcnow()

    # 组织与门店
    org = Organization(organization_id=new_id("organization"), name="和济堂中医馆（演示）",
                       created_by_type="system")
    db.add(org)
    db.flush()
    store = Store(store_id=new_id("store"), organization_id=org.organization_id,
                  store_name="和济堂·滨江店", store_type="tcm_clinic", city="杭州",
                  region="浙江", open_date=(now - timedelta(days=800)).date(),
                  timezone="Asia/Shanghai", currency="CNY", number_of_doctors=3,
                  number_of_staff=4, number_of_rooms=6, business_hours={"mon_sun": "08:30-20:00"})
    db.add(store)
    db.flush()

    # 医生
    doctors = []
    for i, (name, spec) in enumerate([
        ("周明远", ["脾胃病", "内科调理"]), ("林静姝", ["针灸", "颈肩腰腿痛"]),
        ("陈志宏", ["妇科调理", "膏方"]),
    ]):
        d = Doctor(doctor_id=new_id("doctor"), organization_id=org.organization_id,
                   store_id=store.store_id, doctor_name=name, doctor_status=PersonStatus.ACTIVE,
                   specialty=spec, start_date=(now - timedelta(days=700 + i * 100)).date(),
                   created_by_type="system")
        db.add(d)
        doctors.append(d)
    db.flush()

    # 员工
    staffs = []
    for name, role in [("王小雨", StaffRole.CUSTOMER_SERVICE), ("李建国", StaffRole.SALES),
                       ("赵丽", StaffRole.ASSISTANT), ("孙强", StaffRole.MANAGER)]:
        s = Staff(staff_id=new_id("staff"), organization_id=org.organization_id,
                  store_id=store.store_id, name=name, role=role, status=PersonStatus.ACTIVE,
                  start_date=(now - timedelta(days=500)).date(), created_by_type="system")
        db.add(s)
        staffs.append(s)
    db.flush()

    # 服务项目
    services = []
    for name, cat, price, cycle in [
        ("中医内科调理", "内科", 280, 14), ("针灸理疗", "针灸", 180, 7),
        ("推拿正骨", "推拿", 220, 7), ("膏方调理", "膏方", 880, 30),
        ("体质辨识", "体检评估", 120, 90), ("艾灸温养", "艾灸", 160, 10),
    ]:
        svc = Service(service_id=new_id("service"), organization_id=org.organization_id,
                      store_id=store.store_id, service_name=name, service_category=cat,
                      standard_price=Decimal(price), duration_minutes=40,
                      cost=Decimal(price * 0.35), recommended_cycle_days=cycle,
                      recommended_visit_count=6, status=PersonStatus.ACTIVE,
                      created_by_type="system")
        db.add(svc)
        services.append(svc)
    db.flush()

    # 患者（40 人：活跃 / 30/60/90/180 天沉睡 / 流失 / 疗程中断）
    patients = []
    for i in range(40):
        name = random.choice(SURNAMES) + random.choice(GIVEN)
        first = now - timedelta(days=random.randint(60, 700))
        band = i % 8
        if band == 0:
            last = now - timedelta(days=random.randint(3, 25))          # 活跃
            status = CustomerStatus.ACTIVE
        elif band == 1:
            last = now - timedelta(days=random.randint(30, 55))         # 沉睡 30
            status = CustomerStatus.SLEEPING
        elif band == 2:
            last = now - timedelta(days=random.randint(60, 85))         # 沉睡 60
            status = CustomerStatus.SLEEPING
        elif band == 3:
            last = now - timedelta(days=random.randint(90, 170))        # 沉睡 90
            status = CustomerStatus.SLEEPING
        elif band == 4:
            last = now - timedelta(days=random.randint(180, 400))       # 流失
            status = CustomerStatus.LOST
        elif band == 5:
            last = now - timedelta(days=random.randint(200, 500))       # 高价值流失
            status = CustomerStatus.LOST
        else:
            last = now - timedelta(days=random.randint(10, 60))         # 一般
            status = CustomerStatus.ACTIVE if random.random() > 0.3 else CustomerStatus.SLEEPING
        visits_count = max(1, int((last - first).days // random.randint(20, 45)))
        revenue = round(visits_count * random.randint(120, 320), 2)
        p = Patient(
            patient_id=new_id("patient"), organization_id=org.organization_id,
            store_id=store.store_id, name=name,
            gender=random.choice(["male", "female"]),
            mobile=f"13{random.randint(0, 9)}{random.randint(10000000, 99999999)}",
            first_visit_date=first, last_visit_date=last,
            total_visits=visits_count, total_revenue=Decimal(str(revenue)),
            primary_doctor_id=random.choice(doctors).doctor_id,
            primary_staff_id=random.choice(staffs).staff_id,
            customer_status=status, customer_stage="treatment",
            consent_status="granted", contact_status="valid",
            dnc=(i % 37 == 0),   # 少量 DNC 演示合规排除
            source_system="seed",
        )
        db.add(p)
        patients.append(p)
    db.flush()

    # 到店 / 订单 / 付款 / 套餐 / 计划 / 建议
    plans = []
    patient_last_visit = {}
    for idx, p in enumerate(patients):
        n_visits = max(1, min(p.total_visits, 8))
        for vi in range(n_visits):
            visit_at = p.first_visit_date + timedelta(days=(p.last_visit_date - p.first_visit_date).days * vi / max(1, n_visits - 1))
            svc = random.choice(services)
            v = Visit(visit_id=new_id("visit"), organization_id=org.organization_id,
                      store_id=store.store_id, patient_id=p.patient_id,
                      doctor_id=p.primary_doctor_id or doctors[0].doctor_id,
                      staff_id=p.primary_staff_id, visit_at=visit_at,
                      visit_type=VisitType.FIRST_VISIT if vi == 0 else VisitType.FOLLOWUP,
                      service_category=svc.service_category,
                      first_visit_flag=(vi == 0), visit_status=VisitStatus.COMPLETED,
                      source_system="seed")
            db.add(v)
            patient_last_visit[p.patient_id] = v.visit_id
            if vi == 0:
                p.first_visit_date = visit_at
            p.last_visit_date = visit_at if vi == n_visits - 1 else p.last_visit_date
        # 每患者 1-2 笔订单
        for oi in range(1, min(3, n_visits)):
            amount = Decimal(random.randint(200, 2000))
            o = Order(order_id=new_id("order"), organization_id=org.organization_id,
                      store_id=store.store_id, patient_id=p.patient_id,
                      doctor_id=p.primary_doctor_id, original_amount=amount,
                      discount_amount=Decimal(0), final_amount=amount,
                      order_status=OrderStatus.PAID, source_system="seed")
            db.add(o)
            db.add(OrderItem(order_item_id=new_id("order_item"), organization_id=org.organization_id,
                             store_id=store.store_id, order_id=o.order_id,
                             patient_id=p.patient_id, service_id=random.choice(services).service_id,
                             quantity=1, unit_price=amount, line_final_amount=amount,
                             source_system="seed"))
            db.add(Payment(payment_id=new_id("payment"), organization_id=org.organization_id,
                           store_id=store.store_id, order_id=o.order_id, patient_id=p.patient_id,
                           paid_at=p.last_visit_date, amount=amount,
                           payment_method=random.choice(list(PaymentMethod)),
                           status=PaymentStatus.SUCCEEDED, source_system="seed"))
        # 套餐：约一半患者持有剩余次数套餐
        if idx % 2 == 0:
            total_s = Decimal(random.randint(4, 10))
            used_s = Decimal(random.randint(0, int(total_s) - 1))
            pkg = PackageInstance(package_instance_id=new_id("package"),
                                  organization_id=org.organization_id, store_id=store.store_id,
                                  patient_id=p.patient_id, purchase_date=p.last_visit_date,
                                  start_date=p.last_visit_date.date(),
                                  expire_date=(p.last_visit_date + timedelta(days=180)).date(),
                                  total_sessions=total_s, used_sessions=used_s,
                                  remaining_sessions=total_s - used_s,
                                  paid_amount=Decimal(total_s * 150), status=PackageStatus.ACTIVE,
                                  source_system="seed")
            db.add(pkg)
            db.add(PackageUsage(package_usage_id=new_id("package_usage"),
                                organization_id=org.organization_id, store_id=store.store_id,
                                package_instance_id=pkg.package_instance_id, patient_id=p.patient_id,
                                visit_id="", used_at=p.last_visit_date, sessions_used=used_s,
                                remaining_after=total_s - used_s, source_system="seed"))
        # 诊后计划 + 建议（活跃/近沉睡患者有窗口；部分超期）
        if idx % 3 != 1:
            window = 7
            if idx % 3 == 2 and p.customer_status != CustomerStatus.ACTIVE:
                min_d, max_d = (now - timedelta(days=20)).date(), (now - timedelta(days=5)).date()  # 超期
            elif p.customer_status == CustomerStatus.ACTIVE:
                min_d, max_d = now.date() - timedelta(days=1), now.date() + timedelta(days=window)
            else:
                min_d, max_d = now.date(), now.date() + timedelta(days=window)
            plan = TreatmentPlan(treatment_plan_id=new_id("treatment_plan"),
                                 organization_id=org.organization_id, store_id=store.store_id,
                                 patient_id=p.patient_id, visit_id=patient_last_visit.get(p.patient_id, ""), doctor_id=p.primary_doctor_id,
                                 plan_type="调理疗程", recommended_next_visit_min_date=min_d,
                                 recommended_next_visit_max_date=max_d,
                                 recommended_total_visits=6, completed_visits=p.total_visits % 6,
                                 plan_status="active", created_by_type="doctor",
                                 next_action="提醒复诊", next_action_owner=store.store_id)
            db.add(plan)
            plans.append(plan)
            rec = CareRecommendation(care_recommendation_id=new_id("care_recommendation"),
                                     organization_id=org.organization_id, store_id=store.store_id,
                                     visit_id=patient_last_visit.get(p.patient_id, ""), patient_id=p.patient_id, doctor_id=p.primary_doctor_id,
                                     recommended_at=p.last_visit_date,
                                     next_visit_recommended=True, recommended_date=max_d,
                                     appointment_should_be_created=(idx % 2 == 0),
                                     created_by_type="doctor")
            db.add(rec)

    # 预约（活跃患者的未来预约 + 历史完成预约）
    for p in patients[:25]:
        if p.customer_status == CustomerStatus.ACTIVE:
            appt_at = now + timedelta(days=random.randint(1, 7))
            status = AppointmentStatus.CONFIRMED
        else:
            appt_at = p.last_visit_date + timedelta(days=random.randint(1, 20))
            status = random.choice([AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW, AppointmentStatus.CANCELLED])
        db.add(Appointment(appointment_id=new_id("appointment"), organization_id=org.organization_id,
                           store_id=store.store_id, patient_id=p.patient_id,
                           doctor_id=p.primary_doctor_id, staff_id=p.primary_staff_id,
                           service_id=random.choice(services).service_id, appointment_at=appt_at,
                           appointment_source=random.choice(["frontdesk", "wechat", "campaign", "AI"]),
                           status=status, no_show=(status == AppointmentStatus.NO_SHOW),
                           completed_at=(appt_at + timedelta(hours=1)) if status == AppointmentStatus.COMPLETED else None,
                           source_system="seed"))

    # 回访（沉淀 Action→Outcome）
    for p in patients[5:30]:
        db.add(Followup(followup_id=new_id("followup"), organization_id=org.organization_id,
                        store_id=store.store_id, patient_id=p.patient_id,
                        staff_id=random.choice(staffs).staff_id,
                        scheduled_at=now - timedelta(days=random.randint(1, 20)),
                        completed_at=now - timedelta(days=random.randint(1, 15)),
                        reason=FollowupReason.SLEEPING_CUSTOMER if p.customer_status != CustomerStatus.ACTIVE else FollowupReason.REVISIT_REMINDER,
                        channel=random.choice(list(FollowupChannel)),
                        status=FollowupStatus.COMPLETED,
                        result=random.choice([FollowupResult.REPLIED, FollowupResult.INTERESTED,
                                              FollowupResult.APPOINTMENT_CREATED, FollowupResult.NO_ANSWER,
                                              FollowupResult.NOT_INTERESTED]),
                        source_system="seed"))

    # 营销活动
    cmp1 = Campaign(campaign_id=new_id("campaign"), organization_id=org.organization_id,
                    store_id=store.store_id, name="老客回访 Always-on", type=CampaignType.ALWAYS_ON,
                    objective=CampaignObjective.RETENTION, status=CampaignStatus.RUNNING,
                    start_at=now - timedelta(days=15), end_at=now + timedelta(days=45),
                    target_segment={"tags": ["疗程中"]}, source_system="seed")
    cmp2 = Campaign(campaign_id=new_id("campaign"), organization_id=org.organization_id,
                    store_id=store.store_id, name="秋季膏方节", type=CampaignType.SEASONAL,
                    objective=CampaignObjective.PACKAGE_SALES, status=CampaignStatus.DRAFT,
                    start_at=now + timedelta(days=10), end_at=now + timedelta(days=40),
                    budget=Decimal(3000), source_system="seed")
    db.add_all([cmp1, cmp2])
    db.flush()

    # 实验（秋季唤醒实验：control vs treatment）
    exp = Experiment(experiment_id=new_id("experiment"), organization_id=org.organization_id,
                     store_id=store.store_id, name="沉睡客户唤醒实验-8月", engine="recovery",
                     objective="验证企微触达对沉睡客户回店率的增量影响",
                     hypothesis="对沉睡30-90天客户进行企微一对一触达，4周内回店率提升≥8个百分点",
                     primary_metric="visit_rate_28d", status=ExperimentStatus.RUNNING,
                     start_at=now - timedelta(days=7), end_at=now + timedelta(days=21),
                     source_system="seed")
    db.add(exp)
    db.flush()
    sleeping = [p for p in patients if p.customer_status == CustomerStatus.SLEEPING]
    for i, p in enumerate(sleeping[:16]):
        db.add(ExperimentAssignment(experiment_assignment_id=new_id("experiment_assignment"),
                                    organization_id=org.organization_id, store_id=store.store_id,
                                    experiment_id=exp.experiment_id, patient_id=p.patient_id,
                                    group=ExperimentGroup.CONTROL if i % 2 == 0 else ExperimentGroup.TREATMENT_A,
                                    assigned_at=now - timedelta(days=7), source_system="seed"))
    for i, p in enumerate(sleeping[:16]):
        db.add(CampaignAudience(campaign_audience_id=new_id("campaign_audience"),
                                organization_id=org.organization_id, store_id=store.store_id,
                                campaign_id=cmp1.campaign_id, patient_id=p.patient_id,
                                assigned_at=now - timedelta(days=7), segment="沉睡客户",
                                experiment_id=exp.experiment_id,
                                experiment_group=ExperimentGroup.CONTROL if i % 2 == 0 else ExperimentGroup.TREATMENT_A,
                                source_system="seed"))

    # 经营任务（Recovery/Retention/Growth 混合）
    for i, p in enumerate(patients[:20]):
        tt = [TaskType.RECOVERY, TaskType.RETENTION, TaskType.GROWTH][i % 3]
        status = random.choice([TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.COMPLETED])
        db.add(Task(task_id=new_id("task"), organization_id=org.organization_id,
                    store_id=store.store_id, task_type=tt, patient_id=p.patient_id,
                    assigned_to_type=AssignedToType.STAFF, assigned_to_id=random.choice(staffs).staff_id,
                    due_at=now + timedelta(days=1), priority=TaskPriority("SABC"[i % 4]),
                    reason=f"{tt.value}: 沉睡客户唤醒/复诊提醒",
                    expected_value=Decimal(random.randint(200, 1200)),
                    status=status, created_by_type="AI",
                    completed_at=now - timedelta(days=1) if status == TaskStatus.COMPLETED else None,
                    source_system="seed"))

    # Webhook 演示订阅
    db.add(WebhookSubscription(organization_id=org.organization_id,
                               url="http://127.0.0.1:9000/webhook-demo",
                               event_types=None, enabled=True, secret="demo-secret"))

    # ---- 演示账号（登录：boss/boss123，staff/staff123）----
    from .services.auth import hash_password
    from .models import User
    from .models.template import MessageTemplate
    from .models.compliance import ContentReview, ReviewSession

    if db.query(User).count() == 0:
        db.add_all([
            User(user_id=new_id("user"), organization_id=org.organization_id, store_id=store.store_id,
                 username="boss", password_hash=hash_password("boss123"), name="张老板", role="boss",
                 created_by_type="seed"),
            User(user_id=new_id("user"), organization_id=org.organization_id, store_id=store.store_id,
                 username="staff", password_hash=hash_password("staff123"), name="王小雨", role="staff",
                 staff_id=staffs[0].staff_id, created_by_type="seed"),
        ])

    # ---- 话术模板库 ----
    templates = [
        ("沉睡客户激活·企微", "recovery", "enterprise_wechat",
         "尊敬的{患者姓名}，您好！我是{门店}的客服小王。上次调理后有一段时间没见到您了，"
         "近期我们有针对您体质的调理回访，想了解下您最近的身体情况，方便的话可以回复我～"),
        ("复诊提醒·短信", "retention", "sms",
         "【{门店}】{患者姓名}您好，您的复诊时间到了，请在本周内到店复查。回复Y可预约，退订回T。"),
        ("No-show挽回·电话", "retention", "phone",
         "您好{患者姓名}，我是{门店}前台。您之前预约的时间可能错过了，我们帮您重新安排，方便吗？"),
        ("沉睡激活·微信", "recovery", "wechat",
         "{患者姓名}您好，{门店}近期有节气调理活动，想邀请您来免费做一次体质评估～"),
    ]
    for name, ttype, channel, content in templates:
        db.add(MessageTemplate(message_template_id=new_id("message_template"),
                               organization_id=org.organization_id, store_id=store.store_id,
                               name=name, task_type=ttype, channel=channel,
                               content=content, version="v1", created_by_type="seed"))

    # ---- 内容合规审批记录 ----
    db.add_all([
        ContentReview(content_review_id=new_id("content_review"), organization_id=org.organization_id,
                      store_id=store.store_id, campaign_id=cmp2.campaign_id,
                      content_text="秋季膏方节，祖传秘方，根治失眠，限时抢购！",
                      channel="wechat", risk_score=8.0,
                      risk_flags=[{"rule": "绝对化疗效承诺", "matched": "根治", "severity": "high"},
                                  {"rule": "医疗广告违禁词", "matched": "祖传秘方", "severity": "high"},
                                  {"rule": "价格促销敏感", "matched": "限时抢购", "severity": "low"}],
                      status="pending", approved=False, created_by_type="AI"),
        ContentReview(content_review_id=new_id("content_review"), organization_id=org.organization_id,
                      store_id=store.store_id, campaign_id=cmp1.campaign_id,
                      content_text="老客户回访关怀：提醒您按时复诊，保持健康作息。",
                      channel="enterprise_wechat", risk_score=0.0, risk_flags=[],
                      status="approved", approved=True, reviewed_by="boss",
                      reviewed_at=now - timedelta(days=2), review_note="合规，可发",
                      created_by_type="AI"),
    ])

    # ---- 每周复盘记录 ----
    db.add(ReviewSession(review_id=new_id("review"), organization_id=org.organization_id,
                         store_id=store.store_id,
                         period_start=now - timedelta(days=7), period_end=now,
                         engine="all", summary="本周 Recovery 实验第一周：触达 16 人，回店 3 人；"
                                               "建议率偏低的医生需单独沟通。",
                         actions_kept=["企微一对一触达", "复诊短信提醒"],
                         actions_dropped=["群发活动通知（打开率低）"],
                         next_week_plan="补充 No-show 挽回话术实验；下周复盘对比两组回店率。",
                         created_by="boss", created_by_type="staff"))

    db.commit()
    print(f"[seed] 完成：{len(patients)} 患者、{len(doctors)} 医生、{len(services)} 项目、"
          f"{len(plans)} 诊后计划、2 活动、1 实验")