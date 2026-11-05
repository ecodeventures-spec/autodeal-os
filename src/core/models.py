"""Domain models and SaaS Multi-Tenant definitions for NUDHUJ AutoDeal OS."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlanTier(str, Enum):
    FREE = "free"
    GROWTH = "growth"
    BUSINESS = "business"


PLAN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    PlanTier.FREE.value: {
        "id": "free",
        "name_ar": "الباقة المجانية (Starter Free)",
        "name_en": "Starter Free Plan",
        "price_monthly_usd": 0,
        "price_yearly_usd": 0,
        "price_monthly_sar": 0,
        "leads_quota": 25,
        "emails_quota": 50,
        "proposals_quota": 3,
        "campaigns_quota": 1,
        "autopilot_allowed": False,
        "white_label_proposals": False,
        "features_ar": [
            "استكشاف حتى 25 عميلاً محتملاً شهرياً",
            "إرسال حتى 50 رسالة بريد مخصصة شهرياً",
            "إنشاء 3 عروض فنية ومالية تفاعلية شهرياً",
            "محرك التعرف الذكي على هوية وموقع شركتك",
            "سلم الموافقات الآمن ووضع المحاكاة (Dry-Run)",
        ],
        "features_en": [
            "Up to 25 AI-discovered leads / month",
            "Up to 50 hyper-personalized emails / month",
            "3 interactive technical & financial proposals / month",
            "Smart Company Website & Profile Onboarding",
            "Approval Ladder & Safe Dry-Run Sandbox",
        ],
    },
    PlanTier.GROWTH.value: {
        "id": "growth",
        "name_ar": "باقة النمو (Growth Pro)",
        "name_en": "Growth Pro Plan",
        "price_monthly_usd": 79,
        "price_yearly_usd": 63,
        "price_monthly_sar": 299,
        "leads_quota": 500,
        "emails_quota": 2000,
        "proposals_quota": 30,
        "campaigns_quota": 10,
        "autopilot_allowed": True,
        "white_label_proposals": False,
        "features_ar": [
            "استكشاف حتى 500 عميل محتمل شهرياً في أي قطاع",
            "إرسال حتى 2,000 رسالة بريد مع ربط SMTP/IMAP مباشر",
            "30 عرضاً فنياً ومالياً تفاعلياً مع حاسبة العائد ROI",
            "تفعيل الطيار الآلي الكامل والجدولة الخلفية (Autopilot)",
            "إيقاف تلقائي للمتابعات عند رد العميل وتصنيف النوايا",
            "كتالوج خدمات وأسعار مخصص لشركتك",
        ],
        "features_en": [
            "Up to 500 AI-discovered leads / month across any sector",
            "Up to 2,000 automated emails with custom SMTP/IMAP",
            "30 interactive proposals with live ROI calculator",
            "Full Autonomous Autopilot & Background Scheduler",
            "Stop-on-Reply & AI Intent Classification",
            "Custom Company Services & Pricing Catalog",
        ],
    },
    PlanTier.BUSINESS.value: {
        "id": "business",
        "name_ar": "باقة الأعمال والمؤسسات (Enterprise Scale)",
        "name_en": "Enterprise Scale Plan",
        "price_monthly_usd": 199,
        "price_yearly_usd": 159,
        "price_monthly_sar": 749,
        "leads_quota": 10000,
        "emails_quota": 15000,
        "proposals_quota": 500,
        "campaigns_quota": 100,
        "autopilot_allowed": True,
        "white_label_proposals": True,
        "features_ar": [
            "حتى 10,000 عميل و 15,000 رسالة بريد شهرياً",
            "عروض فنية ومالية غير محدودة بهوية شركتك الكاملة (White-Label)",
            "حماية الملكية الفكرية رباعية الطبقات باسم شركتك",
            "تحليل ملفات PDF/Brochures وبناء قاعدة معرفة عميقة",
            "تعدد المستخدمين والصلاحيات وأولوية المعالجة الفائقة",
            "تصدير شامل وتقارير تنفيذية متقدمة",
        ],
        "features_en": [
            "Up to 10,000 leads & 15,000 emails / month",
            "White-Label Interactive Proposals with your own brand",
            "4-Layer IP Watermark Protection under your company name",
            "Deep PDF/Profile Knowledge Base & AI Training",
            "Multi-user workspace & Priority AI Execution",
            "Full CRM Exports & Executive Analytics",
        ],
    },
}


class LeadStatus(str, Enum):
    DISCOVERED = "discovered"
    ENRICHED = "enriched"
    DISQUALIFIED = "disqualified"
    SEQUENCE_DRAFTED = "sequence_drafted"
    APPROVED = "approved"
    ACTIVE_CAMPAIGN = "active_campaign"
    REPLIED = "replied"
    MEETING_BOOKED = "meeting_booked"
    CLOSED_LOST = "closed_lost"
    DO_NOT_CONTACT = "do_not_contact"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    CANCELLED = "cancelled"


class ReplyIntent(str, Enum):
    INTERESTED = "interested"
    OBJECTION = "objection"
    QUESTION = "question"
    OUT_OF_OFFICE = "out_of_office"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"


class Organization(BaseModel):
    id: Optional[int] = None
    name: str
    slug: str
    domain: str = ""
    industry: str = "التقنية والخدمات للأعمال (B2B)"
    plan_tier: str = PlanTier.FREE.value
    billing_cycle: str = "monthly"  # monthly | yearly
    subscription_status: str = "active"
    leads_quota: int = 25
    leads_used: int = 0
    emails_quota: int = 50
    emails_used: int = 0
    proposals_quota: int = 3
    proposals_used: int = 0
    created_at: Optional[str] = None


class User(BaseModel):
    id: Optional[int] = None
    org_id: int = 1
    full_name: str
    email: str
    role: str = "owner"  # owner | admin | member | superadmin
    onboarding_completed: bool = False
    created_at: Optional[str] = None


class ServiceCatalogItem(BaseModel):
    id: str
    name_ar: str
    name_en: str = ""
    category: str = "Core Service"
    description_ar: str = ""
    description_en: str = ""
    unit_price: float = 15000.0
    currency: str = "SAR"
    billing_type: str = "one_time"  # one_time | monthly | annual | milestone
    duration_days: int = 30
    deliverables_ar: List[str] = Field(default_factory=list)
    deliverables_en: List[str] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    company_name_ar: str = "شركة نضج لحلول الأعمال الذكية"
    company_name_en: str = "Nudhuj Autonomous Business Solutions"
    website: str = "https://autodeal.nudhuj.com"
    industry: str = "حلول الأعمال والبرمجيات والاستشارات"
    tagline_ar: str = "نبتكر حلولاً متكاملة تسرّع نمو إيراداتك وتقلل التكاليف التشغيلية"
    tagline_en: str = "Turnkey solutions that accelerate revenue growth and reduce operational overhead"
    about_ar: str = (
        "شركة رائدة متخصصة في تقديم حلول متكاملة للشركات والمؤسسات، نجمع بين الخبرة الميدانية "
        "وأحدث التقنيات لمساعدة عملائنا على تحقيق عائد استثماري ملموس وسريع."
    )
    about_en: str = (
        "A premier B2B partner delivering end-to-end solutions that combine domain expertise "
        "with modern automation for measurable ROI."
    )
    value_proposition_ar: str = (
        "نقدم حلولاً مخصصة تساعد الشركات على زيادة المبيعات ورفع الكفاءة التشغيلية بنسبة 40% خلال 60 يوماً."
    )
    value_proposition_en: str = (
        "We deliver tailored B2B solutions that increase revenue pipeline and operational efficiency by 40% within 60 days."
    )
    sender_persona_ar: str = "مدير تطوير الأعمال والشراكات الاستراتيجية"
    sender_persona_en: str = "VP of Business Development & Strategic Partnerships"
    tone_of_voice: str = "consultative"  # consultative | executive | friendly | technical
    target_industries: List[str] = Field(
        default_factory=lambda: [
            "التجارة الإلكترونية والتجزئة (E-commerce & Retail)",
            "البرمجيات والتقنية (SaaS & Tech)",
            "الرعاية الصحية والعيادات (Healthcare)",
            "الخدمات اللوجستية والصناعة (Logistics & Manufacturing)",
            "العقارات والمقاولات (Real Estate & Construction)",
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
    target_decision_makers: List[str] = Field(
        default_factory=lambda: [
            "الرئيس التنفيذي (CEO)",
            "مدير تطوير الأعمال (Head of Business Development)",
            "مدير العمليات (COO)",
            "مدير المبيعات والتسويق (VP of Sales / CMO)",
        ]
    )
    currency: str = "SAR"
    primary_color: str = "#D4AF37"
    accent_color: str = "#10B981"
    warranty_terms_ar: str = "ضمان شامل ودعم فني وتشغيلي لمدة 12 شهراً مع اتفاقية مستوى خدمة (SLA) باستجابة خلال 4 ساعات عمل."
    warranty_terms_en: str = "12-Month comprehensive warranty & operational support with a 4-hour response SLA."
    services_catalog: List[ServiceCatalogItem] = Field(
        default_factory=lambda: [
            ServiceCatalogItem(
                id="svc-core-package",
                name_ar="الباقة التأسيسية المتكاملة (Turnkey Core Solution)",
                name_en="Turnkey Core Solution Package",
                category="باقة رئيسية",
                description_ar="تحليل الاحتياجات، الإعداد الكامل، التخصيص، والتدريب الميداني لفريق العمل.",
                description_en="Full discovery, turnkey implementation, customization, and team onboarding.",
                unit_price=25000.0,
                currency="SAR",
                billing_type="one_time",
                duration_days=30,
                deliverables_ar=[
                    "دراسة تحليلية شاملة وتصميم الحل المخصص",
                    "التنفيذ والربط التقني والتشغيلي الكامل",
                    "تدريب الفريق وتسليم أدلة التشغيل القياسية",
                ],
                deliverables_en=[
                    "Comprehensive discovery & custom architecture",
                    "Full technical & operational implementation",
                    "Team training & SOP documentation handover",
                ],
            ),
            ServiceCatalogItem(
                id="svc-growth-scale",
                name_ar="باقة التوسع والأتمتة المتقدمة (Enterprise Scale & Automation)",
                name_en="Enterprise Scale & Automation Suite",
                category="باقة متقدمة",
                description_ar="حلول مخصصة للعمليات واسعة النطاق مع ربط الأنظمة، لوحات مؤشرات الأداء، والدعم المخصص.",
                description_en="Enterprise-grade deployment with custom integrations, KPI dashboards, and dedicated SLA.",
                unit_price=55000.0,
                currency="SAR",
                billing_type="one_time",
                duration_days=45,
                deliverables_ar=[
                    "إطلاق شامل متعدد الفروع أو الأقسام",
                    "لوحة تحكم قياسية وتقارير أداء لحظية",
                    "مدير حساب مخصص ودعم فني VIP لمدة عام",
                ],
                deliverables_en=[
                    "Multi-branch / multi-department rollout",
                    "Executive live KPI dashboard & reporting",
                    "Dedicated account manager & 1-year VIP SLA",
                ],
            ),
        ]
    )


class Campaign(BaseModel):
    id: Optional[int] = None
    org_id: int = 1
    name: str
    industry: str
    region: str = "المملكة العربية السعودية"
    language: str = "ar"
    value_proposition: str = ""
    status: str = "active"
    created_at: Optional[str] = None


class Lead(BaseModel):
    id: Optional[int] = None
    org_id: int = 1
    campaign_id: Optional[int] = 1
    company_name: str
    website: str = ""
    industry: str = ""
    region: str = ""
    contact_name: str = ""
    contact_role: str = ""
    contact_email: str = ""
    email_verified: bool = False
    company_summary: str = ""
    pain_points: str = ""
    personalization_hook: str = ""
    qualification_score: int = 0
    score_reasoning: str = ""
    language: str = "ar"
    status: LeadStatus = LeadStatus.DISCOVERED
    proposal_status: str = "none"
    proposal_url: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EmailDraft(BaseModel):
    id: Optional[int] = None
    org_id: int = 1
    lead_id: int
    campaign_id: int = 1
    step_number: int = 1
    subject: str
    body: str
    word_count: int = 0
    language: str = "ar"
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    scheduled_at: Optional[str] = None
    sent_at: Optional[str] = None
    created_at: Optional[str] = None


class InboxReply(BaseModel):
    id: Optional[int] = None
    org_id: int = 1
    lead_id: int
    from_email: str
    subject: str
    body: str
    intent: ReplyIntent = ReplyIntent.QUESTION
    confidence: float = 0.9
    ai_suggested_reply: str = ""
    reply_approved: bool = False
    received_at: Optional[str] = None


class InteractiveProposal(BaseModel):
    id: Optional[int] = None
    org_id: int = 1
    lead_id: Optional[int] = None
    slug: str
    title_ar: str
    title_en: str = ""
    client_company: str
    client_contact: str = ""
    client_role: str = ""
    industry: str = ""
    language: str = "ar"  # ar | en | bilingual
    template_id: str = "universal-b2b"
    hero_subtitle_ar: str = ""
    hero_subtitle_en: str = ""
    executive_summary_ar: str = ""
    executive_summary_en: str = ""
    scope_items: List[Dict[str, Any]] = Field(default_factory=list)
    financial_items: List[Dict[str, Any]] = Field(default_factory=list)
    optional_addons: List[Dict[str, Any]] = Field(default_factory=list)
    payment_schedule: List[Dict[str, Any]] = Field(default_factory=list)
    execution_roadmap: List[Dict[str, Any]] = Field(default_factory=list)
    roi_projection: Dict[str, Any] = Field(default_factory=dict)
    warranty_terms_ar: str = ""
    warranty_terms_en: str = ""
    subtotal_amount: float = 0.0
    discount_percent: float = 0.0
    tax_percent: float = 15.0
    total_amount: float = 0.0
    currency: str = "SAR"
    valid_days: int = 15
    white_label: bool = False
    provider_name_ar: str = ""
    provider_name_en: str = ""
    primary_color: str = "#D4AF37"
    status: str = "generated"  # draft | generated | sent | viewed | accepted
    views_count: int = 0
    accepted_at: Optional[str] = None
    accepted_by: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EnrichmentResult(BaseModel):
    company_summary: str = Field(description="Concise summary of what the company does")
    pain_points: str = Field(description="Likely business pain points relevant to our solution")
    personalization_hook: str = Field(description="Specific observation about the company to use as an icebreaker")
    contact_role_guess: str = Field(default="المدير التنفيذي / مدير تطوير الأعمال")
    qualification_score: int = Field(ge=0, le=100, description="ICP fit score from 0 to 100")
    score_reasoning: str = Field(description="Why this score was assigned")


class SequenceStepSchema(BaseModel):
    step_number: int
    subject: str
    body: str


class GeneratedSequenceSchema(BaseModel):
    steps: List[SequenceStepSchema]


class ReplyClassificationSchema(BaseModel):
    intent: ReplyIntent
    confidence: float
    reasoning: str
    suggested_reply: str
