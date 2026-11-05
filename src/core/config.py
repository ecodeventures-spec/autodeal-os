"""Configuration loader and persistent saver for NUDHUJ AutoDeal OS (autodeal.nudhuj.com)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.core.models import CompanyProfile

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


class SystemConfig(BaseModel):
    name: str = "NUDHUJ AutoDeal OS"
    domain: str = "https://autodeal.nudhuj.com"
    default_language: str = "ar"
    dry_run: bool = True
    auto_approve_sequences: bool = False
    autopilot_enabled: bool = False
    autopilot_interval_minutes: int = 15


class LLMConfig(BaseModel):
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    max_output_tokens: int = 1500
    gemini_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"


class ICPConfig(BaseModel):
    min_qualification_score: int = 65
    target_industries: List[str] = Field(
        default_factory=lambda: [
            "التجارة الإلكترونية والتجزئة (E-commerce & Retail)",
            "البرمجيات كخدمة والتقنية (SaaS & Tech)",
            "الخدمات المالية والتقنية المالية (FinTech)",
            "الرعاية الصحية والعيادات (HealthTech)",
            "الخدمات اللوجستية وسلاسل الإمداد (Logistics)",
            "العقارات والمقاولات والضيافة (Real Estate & Hospitality)",
        ]
    )
    target_regions: List[str] = Field(
        default_factory=lambda: [
            "المملكة العربية السعودية",
            "الإمارات العربية المتحدة",
            "مصر",
            "الخليج والشرق الأوسط (MENA)",
            "Global",
        ]
    )
    value_proposition_ar: str = (
        "نقدم حلول أتمتة ذكية ومتكاملة تساعد الشركات على زيادة المبيعات "
        "وتقليل تكاليف التشغيل بنسبة 40% خلال 60 يوماً."
    )
    value_proposition_en: str = (
        "We build autonomous workflow and revenue growth systems that help B2B teams "
        "increase qualified pipeline and reduce operational overhead by 40% within 60 days."
    )
    sender_persona_ar: str = "مستشار تطوير الأعمال والشراكات الاستراتيجية"
    sender_persona_en: str = "VP of Business Development & Strategic Growth"


class WriterConfig(BaseModel):
    sequence_steps: int = 3
    step_delays_days: List[int] = Field(default_factory=lambda: [0, 3, 7])
    max_words_step_1: int = 75
    max_words_step_2: int = 50
    max_words_step_3: int = 40
    banned_buzzwords_en: List[str] = Field(
        default_factory=lambda: [
            "I hope this email finds you well",
            "synergy",
            "game-changer",
            "revolutionary",
            "cutting-edge",
            "delve",
            "tapestry",
            "unlock your potential",
            "paradigm shift",
        ]
    )
    banned_buzzwords_ar: List[str] = Field(
        default_factory=lambda: [
            "أتمنى أن تصلك رسالتي هذه وأنت بخير",
            "ثورة غير مسبوقة",
            "قفزة نوعية خارقة",
            "عصر جديد من التميز",
            "نحن الأفضل في العالم",
        ]
    )


class SenderConfig(BaseModel):
    daily_send_cap: int = 40
    min_delay_seconds: int = 120
    max_delay_seconds: int = 360
    sending_window_start_hour: int = 9
    sending_window_end_hour: int = 17
    timezone: str = "Asia/Riyadh"
    stop_on_reply: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    sender_name: str = "فريق تطوير الأعمال | نضج"
    sender_email: str = "sales@nudhuj.com"
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    calendar_booking_link: str = "https://calendly.com/nudhuj/discovery-call"


class AppSettings(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    company: CompanyProfile = Field(default_factory=CompanyProfile)
    icp: ICPConfig = Field(default_factory=ICPConfig)
    writer: WriterConfig = Field(default_factory=WriterConfig)
    sender: SenderConfig = Field(default_factory=SenderConfig)
    database_path: str = "data/autodeal_os.db"
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000


def load_settings(config_path: Path | None = None) -> AppSettings:
    """Load configuration from YAML file and override with environment variables."""
    yaml_path = config_path or (BASE_DIR / "config" / "settings.yaml")
    raw_data: Dict[str, Any] = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

    settings = AppSettings(**raw_data)

    # Environment variable overrides
    if os.getenv("DRY_RUN") is not None:
        settings.system.dry_run = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    if os.getenv("AI_PROVIDER"):
        settings.llm.provider = os.getenv("AI_PROVIDER", settings.llm.provider)
    if os.getenv("AI_MODEL"):
        settings.llm.model = os.getenv("AI_MODEL", settings.llm.model)

    settings.llm.gemini_api_key = os.getenv("GEMINI_API_KEY", settings.llm.gemini_api_key)
    settings.llm.openai_api_key = os.getenv("OPENAI_API_KEY", settings.llm.openai_api_key)
    settings.llm.ollama_base_url = os.getenv("OLLAMA_BASE_URL", settings.llm.ollama_base_url)

    settings.sender.smtp_host = os.getenv("SMTP_HOST", settings.sender.smtp_host)
    settings.sender.smtp_port = int(os.getenv("SMTP_PORT", str(settings.sender.smtp_port)))
    settings.sender.smtp_username = os.getenv("SMTP_USERNAME", settings.sender.smtp_username)
    settings.sender.smtp_password = os.getenv("SMTP_PASSWORD", settings.sender.smtp_password)
    settings.sender.sender_name = os.getenv("SENDER_NAME", settings.sender.sender_name)
    settings.sender.sender_email = os.getenv("SENDER_EMAIL", settings.sender.sender_email)

    settings.sender.imap_host = os.getenv("IMAP_HOST", settings.sender.imap_host)
    settings.sender.imap_port = int(os.getenv("IMAP_PORT", str(settings.sender.imap_port)))
    settings.sender.imap_username = os.getenv("IMAP_USERNAME", settings.sender.imap_username)
    settings.sender.imap_password = os.getenv("IMAP_PASSWORD", settings.sender.imap_password)
    settings.sender.calendar_booking_link = os.getenv(
        "CALENDAR_BOOKING_LINK", settings.sender.calendar_booking_link
    )

    settings.database_path = os.getenv("DATABASE_PATH", settings.database_path)
    settings.dashboard_host = os.getenv("DASHBOARD_HOST", settings.dashboard_host)
    settings.dashboard_port = int(os.getenv("DASHBOARD_PORT", str(settings.dashboard_port)))

    return settings


def save_settings(settings: AppSettings, config_path: Path | None = None) -> None:
    """Persist current settings back to settings.yaml so user configuration survives restarts."""
    yaml_path = config_path or (BASE_DIR / "config" / "settings.yaml")
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump()
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
