"""ClinicOS 全局配置（.env 驱动）。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ClinicOS"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # 数据库：默认 SQLite（零配置）；生产可切换 PostgreSQL
    database_url: str = "sqlite:///./clinicos.db"

    # 服务端到服务端认证：逗号分隔的 API Key
    api_keys: str = "dev-key-change-me"
    # API Key → organization_id 映射（JSON 对象）；生产环境必填
    api_key_org_map: str = "{}"

    # Webhook
    webhook_secret: str = "dev-webhook-secret-change-me"
    webhook_base_url: str = "http://127.0.0.1:8000"
    webhook_retry_base_seconds: float = 5.0
    webhook_max_retries: int = 5
    webhook_delivery_mode: str = "log"  # log | http

    # 认证（登录/角色权限）
    auth_secret: str = 'dev-auth-secret-change-me'
    token_ttl_hours: int = 24 * 7

    # 每日自动任务调度
    task_schedule_enabled: bool = True
    task_schedule_hour: int = 9
    task_schedule_minute: int = 0
    task_daily_recovery_limit: int = 30

    # 反馈图片上传目录
    upload_dir: str = './uploads'

    # 种子数据
    seed_demo_data: bool = True

    # ---------- RevOS ----------
    # AI 内容生成 Provider：mock | http
    revos_text_provider: str = "mock"
    revos_image_provider: str = "mock"
    # 通用 HTTP Provider 配置（供应商通过环境变量注入，不写死密钥）
    revos_text_provider_url: str = ""
    revos_text_provider_api_key: str = ""
    revos_text_provider_model: str = ""
    revos_image_provider_url: str = ""
    revos_image_provider_api_key: str = ""
    revos_image_provider_model: str = ""
    revos_llm_timeout_seconds: float = 30.0
    revos_llm_max_retries: int = 2

    # 企微 Gateway：simulator | http
    revos_wecom_mode: str = "simulator"
    revos_wecom_corpid: str = ""
    revos_wecom_secret: str = ""
    revos_wecom_api_base: str = "https://qyapi.weixin.qq.com/cgi-bin"
    revos_wecom_agent_id: str = ""

    # 小程序：wx.login code2session
    revos_wx_appid: str = ""
    revos_wx_secret: str = ""
    revos_mp_ticket_ttl_seconds: int = 3600

    # 运营参数
    revos_dormant_days: int = 60            # 沉睡召回：无到店/消费天数阈值
    revos_touch_frequency_days: int = 14    # 主动营销触达频控
    revos_opportunity_ttl_days: int = 30    # 机会有效期
    revos_arbitration_cycle_days: int = 7   # 仲裁周期（同一周期只选一个主要外部计划）
    revos_staff_daily_touch_limit: int = 20  # 员工当日触达上限
    revos_store_daily_touch_limit: int = 200 # 门店当日触达上限
    revos_min_experiment_sample: int = 30   # 实验最低样本（不足只给方向性结论）
    revos_observation_window_days: int = 30 # 归因观察窗口

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()