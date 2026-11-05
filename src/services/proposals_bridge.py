"""Universal Proposals Engine & Bridge Service: Generates interactive B2B Technical & Financial Proposals for ANY company and industry."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import secrets
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.core.config import AppSettings
from src.core.llm import UnifiedLLMClient
from src.core.models import InteractiveProposal, Lead


UNIVERSAL_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "tpl-universal-turnkey",
        "segment_code": "B2B-CORE",
        "name_ar": "الحل المؤسسي المتكامل وتطوير الأعمال (Turnkey B2B Solution)",
        "name_en": "Turnkey B2B Enterprise Solution",
        "keywords": ["شركة", "أعمال", "استشارات", "تطوير", "حلول", "enterprise", "consulting", "solution"],
        "unit_price_sar": 35000,
    },
    {
        "id": "tpl-saas-automation",
        "segment_code": "SAAS-AI",
        "name_ar": "الأتمتة الرقمية والبرمجيات والذكاء الاصطناعي (SaaS & AI)",
        "name_en": "Digital Automation, Cloud & AI Systems",
        "keywords": ["برمجيات", "تقنية", "ذكاء", "أتمتة", "سحابي", "منصة", "تطبيق", "saas", "ai", "software", "cloud"],
        "unit_price_sar": 45000,
    },
    {
        "id": "tpl-marketing-growth",
        "segment_code": "GROWTH",
        "name_ar": "النمو التسويقي وإدارة الحملات والهوية (Growth & Branding)",
        "name_en": "Revenue Growth, Performance Marketing & Branding",
        "keywords": ["تسويق", "مبيعات", "إعلان", "هوية", "متجر", "تجارة", "marketing", "branding", "ecommerce"],
        "unit_price_sar": 28000,
    },
    {
        "id": "tpl-contracting-supply",
        "segment_code": "SUPPLY",
        "name_ar": "التوريد المؤسسي والمقاولات والتجهيز (Supply & Contracting)",
        "name_en": "Enterprise Supply Chain, Fit-out & Contracting",
        "keywords": ["توريد", "مقاولات", "بناء", "عقار", "لوجست", "شحن", "مصنع", "supply", "logistics", "construction"],
        "unit_price_sar": 65000,
    },
    {
        "id": "tpl-luxury-fragrance",
        "segment_code": "LUX-VEND",
        "name_ar": "مكائن الخدمة الذاتية والحلول الذكية (Smart Self-Service Kiosks)",
        "name_en": "Smart Self-Service Machines & Interactive Kiosks",
        "keywords": ["عطور", "مكائن", "بيع ذاتي", "تجميل", "بادل", "قهوة", "vending", "kiosk", "fragrance"],
        "unit_price_sar": 68500,
    },
]


class ExtractedProposalSpec(BaseModel):
    recommended_template_id: str = Field(default="tpl-universal-turnkey")
    client_company_ar: str
    client_company_en: str
    contact_person: str
    recommended_quantity: int = Field(default=1, ge=1, le=500)
    unit_price_sar: int = Field(default=35000)
    discount_percent: int = Field(default=0, ge=0, le=35)
    payment_preset_id: str = Field(default="standard-50-30-20")
    warranty_years: int = Field(default=1, ge=1, le=5)
    delivery_weeks: str = Field(default="3 - 4 أسابيع عمل")
    executive_summary_ar: str
    executive_summary_en: str
    key_customizations_ar: List[str]
    follow_up_email_subject: str
    follow_up_email_body: str


class ProposalsBridgeService:
    """
    Analyzes meeting transcripts or client notes, combines them with the tenant's
    CompanyProfile & Services Catalog, and generates an InteractiveProposal.
    """

    def __init__(self, settings: AppSettings, llm: UnifiedLLMClient) -> None:
        self.settings = settings
        self.llm = llm

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF\s-]", "", text).strip().lower()
        slug = re.sub(r"[\s_]+", "-", slug)
        if not re.search(r"[a-z0-9]", slug):
            slug = f"deal-{int(datetime.now(timezone.utc).timestamp())}"
        else:
            slug = re.sub(r"[^a-z0-9-]", "", slug).strip("-")
            if not slug:
                slug = f"deal-{secrets.token_hex(3)}"
        return f"{slug[:28]}-{secrets.token_hex(2)}"

    def _match_template(self, text: str, industry: str) -> Dict[str, Any]:
        combined = f"{text} {industry}".lower()
        for tpl in UNIVERSAL_TEMPLATES:
            for kw in tpl["keywords"]:
                if kw.lower() in combined:
                    return tpl
        return UNIVERSAL_TEMPLATES[0]

    async def analyze_transcript_and_create_proposal(
        self,
        lead: Lead,
        transcript_text: str,
        custom_notes: str = "",
        tenant_profile: Optional[Dict[str, Any]] = None,
        white_label: bool = False,
    ) -> Dict[str, Any]:
        cp = tenant_profile or self.settings.company.model_dump()
        provider_ar = cp.get("company_name_ar") or self.settings.company.company_name_ar
        provider_en = cp.get("company_name_en") or self.settings.company.company_name_en
        provider_industry = cp.get("industry") or self.settings.company.industry
        currency = cp.get("currency") or "SAR"
        catalog = cp.get("services_catalog") or []

        matched_tpl = self._match_template(
            f"{transcript_text} {custom_notes} {provider_industry}", lead.industry
        )
        slug = self._slugify(lead.company_name)
        local_url = f"/c/{slug}"
        prod_url = f"{self.settings.system.domain.rstrip('/')}/c/{slug}"

        # Extract quantity from transcript if mentioned
        qty_match = re.search(r"(\d+)\s*(?:فرع|فروع|وحدة|وحدات|جهاز|أجهزة|باقة|رخصة|branches|units|licenses)", transcript_text)
        qty = int(qty_match.group(1)) if qty_match else 1

        # Determine base pricing from tenant's services catalog if available
        if catalog and len(catalog) > 0:
            primary_service = catalog[min(1, len(catalog) - 1)]
            base_unit_price = int(float(primary_service.get("unit_price", matched_tpl["unit_price_sar"])))
            service_title_ar = primary_service.get("name_ar", matched_tpl["name_ar"])
            service_title_en = primary_service.get("name_en", matched_tpl["name_en"])
        else:
            base_unit_price = matched_tpl["unit_price_sar"]
            service_title_ar = matched_tpl["name_ar"]
            service_title_en = matched_tpl["name_en"]

        discount = 10 if qty >= 3 else (5 if qty >= 2 else 0)

        def _fallback_spec() -> ExtractedProposalSpec:
            total_before = qty * base_unit_price
            total_after = int(total_before * (1 - discount / 100))
            return ExtractedProposalSpec(
                recommended_template_id=matched_tpl["id"],
                client_company_ar=lead.company_name,
                client_company_en=lead.company_name,
                contact_person=lead.contact_name or "الإدارة التنفيذية",
                recommended_quantity=qty,
                unit_price_sar=base_unit_price,
                discount_percent=discount,
                payment_preset_id="standard-50-30-20",
                warranty_years=1,
                delivery_weeks="3 - 4 أسابيع عمل",
                executive_summary_ar=(
                    f"بناءً على الاجتماع المثمر مع فريق ({lead.company_name})، يسعدنا في ({provider_ar}) "
                    f"تقديم هذا العرض الفني والمالي المتكامل لتنفيذ ({service_title_ar}) بما يحقق أهدافكم التشغيلية والاستراتيجية."
                ),
                executive_summary_en=(
                    f"Following our discovery session with {lead.company_name}, {provider_en} is pleased to present "
                    f"this turnkey technical and financial proposal for {service_title_en}."
                ),
                key_customizations_ar=[
                    f"تخصيص الحل بالكامل ليتوافق مع متطلبات ({lead.company_name}) في قطاع ({lead.industry})",
                    f"توريد وتنفيذ عدد ({qty}) حزمة/وحدة عمل متكاملة من ({service_title_ar})",
                    "ربط مباشر بلوحة التقارير ومؤشرات الأداء اللحظية",
                    cp.get("warranty_terms_ar") or "ضمان شامل ودعم فني وتشغيلي لمدة 12 شهراً مع SLA خلال 4 ساعات",
                ],
                follow_up_email_subject=f"العرض الفني والمالي المخصص لشركة {lead.company_name} | {provider_ar}",
                follow_up_email_body=(
                    f"مرحباً {lead.contact_name or 'فريق الإدارة'}،\n\n"
                    f"شكراً لوقتكم الثمين خلال اجتماعنا. بناءً على ما تم نقاشه، قمنا في ({provider_ar}) بإعداد العرض الفني والمالي التفاعلي المخصص لشركة {lead.company_name}:\n\n"
                    f"🔗 رابط استعراض العرض التفاعلي المباشر:\n{prod_url}\n\n"
                    f"📌 أبرز ملامح العرض:\n"
                    f"• الحل الموصى به: {service_title_ar} (الكمية: {qty})\n"
                    f"• صافي الاستثمار بعد الخصم ({discount}%): {total_after:,} {currency} (غير شامل الضريبة)\n"
                    f"• مدة التنفيذ والتسليم: 3 - 4 أسابيع عمل\n\n"
                    f"نسعد بمراجعتكم واعتماد العرض مباشرة عبر الرابط أعلاه.\n\n"
                    f"خالص التحية،\n{self.settings.sender.sender_name}\n{provider_ar}"
                ),
            )

        prompt = (
            f"Analyze this sales discovery call transcript and build a B2B proposal specification:\n"
            f"- Our Provider Company: {provider_ar} ({provider_industry})\n"
            f"- Prospect Company: {lead.company_name} ({lead.industry})\n"
            f"- Contact: {lead.contact_name} ({lead.contact_role})\n"
            f"- Recommended Service: {service_title_ar} (Base price: {base_unit_price} {currency})\n"
            f"- Proposal Interactive Link: {prod_url}\n"
            f"- Call Transcript: {transcript_text}\n"
            f"- Additional Notes: {custom_notes}\n"
        )

        spec = await self.llm.generate_structured(
            prompt=prompt,
            schema_cls=ExtractedProposalSpec,
            system_instruction="You are a Principal B2B Solutions Architect & Deal Desk Director. Output valid JSON.",
            fallback_factory=_fallback_spec,
        )

        subtotal = float(spec.recommended_quantity * spec.unit_price_sar)
        discounted = subtotal * (1.0 - (spec.discount_percent / 100.0))
        vat_amount = round(discounted * 0.15, 2)
        grand_total = round(discounted + vat_amount, 2)

        # Build full scope & financial items from tenant catalog or spec
        financial_items = [
            {
                "item_ar": service_title_ar,
                "item_en": service_title_en,
                "description_ar": spec.executive_summary_ar,
                "qty": spec.recommended_quantity,
                "unit_price": spec.unit_price_sar,
                "total": subtotal,
            }
        ]
        if catalog and len(catalog) > 1:
            optional_addons = [
                {
                    "id": item.get("id", f"addon-{idx}"),
                    "name_ar": item.get("name_ar", "باقة إضافية"),
                    "name_en": item.get("name_en", "Optional Add-on"),
                    "description_ar": item.get("description_ar", ""),
                    "price": float(item.get("unit_price", 12000)),
                }
                for idx, item in enumerate(catalog)
            ]
        else:
            optional_addons = [
                {
                    "id": "addon-sla-vip",
                    "name_ar": "باقة الدعم الفني والتشغيلي المميز VIP SLA (24/7)",
                    "name_en": "24/7 VIP Priority SLA & Dedicated Account Team",
                    "description_ar": "فريق دعم مخصص مع زيارات ميدانية دورية واستجابة فورية خلال ساعتين.",
                    "price": 12500.0,
                },
                {
                    "id": "addon-analytics",
                    "name_ar": "الربط المتقدم مع أنظمة الـ ERP ولوحة ذكاء الأعمال (BI)",
                    "name_en": "Custom ERP/CRM Integration & Executive BI Dashboard",
                    "description_ar": "مزامنة ثنائية الاتجاه للبيانات والتقارير المالية والتشغيلية.",
                    "price": 9500.0,
                },
            ]

        payment_schedule = [
            {
                "stage_ar": "الدفعة الأولى — توقيع العقد وبدء التنفيذ",
                "stage_en": "Milestone 1 — Contract Signature & Kickoff",
                "percent": 50,
                "amount": round(grand_total * 0.50, 2),
                "trigger_ar": "عند اعتماد العرض وتوقيع الاتفاقية الرسمية",
            },
            {
                "stage_ar": "الدفعة الثانية — تسليم المرحلة الأساسية والفحص الفني",
                "stage_en": "Milestone 2 — Core Delivery & QA Sign-off",
                "percent": 30,
                "amount": round(grand_total * 0.30, 2),
                "trigger_ar": "عند اكتمال التجهيز الأساسي ومراجعة المخرجات",
            },
            {
                "stage_ar": "الدفعة الختامية — التشغيل الفعلي والتسليم النهائي",
                "stage_en": "Milestone 3 — Final Go-Live & Handover",
                "percent": 20,
                "amount": round(grand_total * 0.20, 2),
                "trigger_ar": "عند الإطلاق النهائي وتدريب الفريق",
            },
        ]

        execution_roadmap = [
            {
                "phase": "المرحلة 1",
                "title_ar": "التحليل الهندسي وتثبيت المتطلبات",
                "duration": "الأسبوع 1",
                "deliverable": "وثيقة نطاق العمل التفصيلية وخطة المشروع",
            },
            {
                "phase": "المرحلة 2",
                "title_ar": "التنفيذ والتخصيص وبناء الحل",
                "duration": "الأسبوع 2 - 3",
                "deliverable": "إنجاز كامل البنود الفنية والربط التشغيلي",
            },
            {
                "phase": "المرحلة 3",
                "title_ar": "الاختبار، التدريب، والإطلاق الرسمي",
                "duration": "الأسبوع 4",
                "deliverable": "محضر التسليم النهائي وبدء سريان الضمان",
            },
        ]

        interactive_proposal = InteractiveProposal(
            org_id=lead.org_id or 1,
            lead_id=lead.id,
            slug=slug,
            title_ar=f"العرض الفني والمالي: {service_title_ar}",
            title_en=f"Technical & Commercial Proposal: {service_title_en}",
            client_company=lead.company_name,
            client_contact=spec.contact_person,
            client_role=lead.contact_role or "الإدارة التنفيذية",
            industry=lead.industry,
            language=lead.language or "ar",
            template_id=spec.recommended_template_id,
            hero_subtitle_ar=f"مقدم حصرياً من {provider_ar} إلى {lead.company_name}",
            hero_subtitle_en=f"Exclusively prepared by {provider_en} for {lead.company_name}",
            executive_summary_ar=spec.executive_summary_ar,
            executive_summary_en=spec.executive_summary_en,
            scope_items=[
                {"title_ar": item, "included": True} for item in spec.key_customizations_ar
            ],
            financial_items=financial_items,
            optional_addons=optional_addons,
            payment_schedule=payment_schedule,
            execution_roadmap=execution_roadmap,
            roi_projection={
                "estimated_monthly_savings_or_gain": round(grand_total * 0.28, 0),
                "payback_months": 3.5,
                "first_year_roi_percent": 240,
            },
            warranty_terms_ar=cp.get("warranty_terms_ar")
            or "ضمان شامل لمدة 12 شهراً مع دعم فني واتفاقية مستوى خدمة SLA.",
            warranty_terms_en=cp.get("warranty_terms_en")
            or "12-Month comprehensive warranty & SLA support.",
            subtotal_amount=subtotal,
            discount_percent=float(spec.discount_percent),
            tax_percent=15.0,
            total_amount=grand_total,
            currency=currency,
            valid_days=15,
            white_label=white_label,
            provider_name_ar=provider_ar,
            provider_name_en=provider_en,
            primary_color=cp.get("primary_color") or "#D4AF37",
            status="generated",
        )

        return {
            "lead_id": lead.id,
            "ref_code": f"NUD-{matched_tpl['segment_code']}-{lead.id or 1:03d}",
            "slug": slug,
            "template": matched_tpl,
            "spec": spec.model_dump(),
            "interactive_proposal": interactive_proposal,
            "financial_summary": {
                "quantity": spec.recommended_quantity,
                "unit_price_sar": spec.unit_price_sar,
                "discount_percent": spec.discount_percent,
                "subtotal_sar": subtotal,
                "discounted_subtotal_sar": discounted,
                "vat_15_sar": vat_amount,
                "grand_total_sar": grand_total,
                "currency": currency,
            },
            "proposal_urls": {
                "local_url": local_url,
                "production_url": prod_url,
                "admin_studio_url": "/app#proposals",
            },
        }
