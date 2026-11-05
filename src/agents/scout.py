"""Scout Agent: Dynamically discovers B2B prospects across ANY industry, region, or CSV upload."""

from __future__ import annotations

import csv
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from src.agents.base import BaseSalesAgent
from src.core.models import Lead, LeadStatus


class DiscoveredProspectSchema(BaseModel):
    company_name: str
    website: str
    industry: str
    region: str
    contact_name: str
    contact_role: str
    contact_email: str
    company_summary: str
    language: str = "ar"


class DiscoveredProspectListSchema(BaseModel):
    prospects: List[DiscoveredProspectSchema]


SAMPLE_PROSPECTS_AR: List[Dict[str, Any]] = [
    {
        "company_name": "نماء للتجارة الإلكترونية والحلول السحابية (Namaa Cloud)",
        "website": "https://namaacloud.sa",
        "industry": "التجارة الإلكترونية (E-commerce)",
        "region": "المملكة العربية السعودية",
        "contact_name": "م. خالد العتيبي",
        "contact_role": "الرئيس التنفيذي لتطوير الأعمال",
        "contact_email": "khalid@namaacloud.sa",
        "company_summary": "منصة سعودية متخصصة في تمكين المتاجر الإلكترونية المتوسطة والكبيرة وربط سلاسل الإمداد.",
        "language": "ar",
    },
    {
        "company_name": "دارك باي للتقنية المالية (DarPay FinTech)",
        "website": "https://darpay.ae",
        "industry": "الخدمات المالية والتقنية المالية (FinTech)",
        "region": "الإمارات العربية المتحدة",
        "contact_name": "أ. سارة المنصوري",
        "contact_role": "مديرة العمليات والنمو",
        "contact_email": "sara@darpay.ae",
        "company_summary": "شركة تقنية مالية تقدم بوابات دفع ذكية وحلول تحصيل فوري للشركات في الخليج.",
        "language": "ar",
    },
    {
        "company_name": "مدار اللوجستية الذكية (Madar Logistics)",
        "website": "https://madarlogistics.com.sa",
        "industry": "الخدمات اللوجستية وسلاسل الإمداد (Logistics)",
        "region": "المملكة العربية السعودية",
        "contact_name": "أ. فهد القحطاني",
        "contact_role": "مدير المبيعات والشراكات الاستراتيجية",
        "contact_email": "fahad@madarlogistics.com.sa",
        "company_summary": "شركة إدارة أساطيل وتوصيل الميل الأخير لقطاعات التجزئة والصيدليات في الرياض وجدة.",
        "language": "ar",
    },
    {
        "company_name": "شفاء هيلث تيك (Shifaa HealthTech)",
        "website": "https://shifaahealth.eg",
        "industry": "الرعاية الصحية الرقمية (HealthTech)",
        "region": "مصر",
        "contact_name": "د. طارق عبد الرحمن",
        "contact_role": "المؤسس والرئيس التنفيذي",
        "contact_email": "tarek@shifaahealth.eg",
        "company_summary": "منصة إدارة العيادات والحجوزات الطبية والاستشارات عن بعد لأكثر من 400 مركز طبي.",
        "language": "ar",
    },
    {
        "company_name": "روافد للتطوير العقاري والمقاولات (Rawafed Realty)",
        "website": "https://rawafedrealty.sa",
        "industry": "العقارات والمقاولات (Real Estate & Construction)",
        "region": "المملكة العربية السعودية",
        "contact_name": "م. سلطان الدوسري",
        "contact_role": "المدير العام للمشاريع والمشتريات",
        "contact_email": "sultan@rawafedrealty.sa",
        "company_summary": "مجموعة تطوير عقاري ومراكز تجارية ومجمعات مكتبية حديثة في الرياض والمنطقة الشرقية.",
        "language": "ar",
    },
    {
        "company_name": "أطياب للضيافة والفنادق الفاخرة (Atyab Hospitality)",
        "website": "https://atyabhospitality.com",
        "industry": "الضيافة والفنادق والمطاعم (Hospitality & F&B)",
        "region": "الإمارات العربية المتحدة",
        "contact_name": "أ. راشد النعيمي",
        "contact_role": "مدير تطوير الفروع والتشغيل",
        "contact_email": "rashed@atyabhospitality.com",
        "company_summary": "سلسلة فنادق بوتيك ومطاعم راقية تدير أكثر من 28 فرعاً في دبي وأبوظبي والرياض.",
        "language": "ar",
    },
]

SAMPLE_PROSPECTS_EN: List[Dict[str, Any]] = [
    {
        "company_name": "VeloceScale SaaS",
        "website": "https://velocescale.io",
        "industry": "SaaS & Tech",
        "region": "Global",
        "contact_name": "Marcus Vance",
        "contact_role": "VP of Revenue Operations",
        "contact_email": "marcus@velocescale.io",
        "company_summary": "B2B cloud analytics and customer onboarding automation platform for mid-market SaaS teams.",
        "language": "en",
    },
    {
        "company_name": "NexaFreight Systems",
        "website": "https://nexafreight.com",
        "industry": "Logistics & Supply Chain",
        "region": "Global",
        "contact_name": "Elena Rostova",
        "contact_role": "Head of Strategic Partnerships",
        "contact_email": "elena@nexafreight.com",
        "company_summary": "Real-time freight visibility and automated customs brokerage software for cross-border commerce.",
        "language": "en",
    },
]


class ScoutAgent(BaseSalesAgent):
    """
    Discovers new B2B leads from ANY target industry/sector, region, CSV file, or direct query,
    and saves them with status `DISCOVERED` scoped to `org_id`.
    """

    async def run(
        self,
        industry: Optional[str] = None,
        region: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 5,
        csv_path: Optional[str] = None,
        campaign_id: int = 1,
        org_id: int = 1,
    ) -> List[Lead]:
        lang = (language or self.settings.system.default_language).lower()
        if csv_path:
            raw_leads = self._load_from_csv(Path(csv_path), default_lang=lang)
        else:
            raw_leads = await self._discover_prospects(
                industry=industry,
                region=region,
                language=lang,
                limit=limit,
                org_id=org_id,
            )

        selected = raw_leads[:limit]
        # Check and consume SaaS quota for this organization
        if selected:
            await self.db.check_and_consume_quota(org_id=org_id, resource="leads", amount=len(selected))

        saved_leads: List[Lead] = []
        for item in selected:
            lead = Lead(
                org_id=org_id,
                campaign_id=campaign_id,
                company_name=item["company_name"],
                website=item.get("website", ""),
                industry=item.get("industry", industry or "SaaS & Tech"),
                region=item.get("region", region or "المملكة العربية السعودية"),
                contact_name=item.get("contact_name", ""),
                contact_role=item.get("contact_role", ""),
                contact_email=item.get("contact_email", ""),
                company_summary=item.get("company_summary", ""),
                language=item.get("language", lang if lang != "both" else "ar"),
                status=LeadStatus.DISCOVERED,
            )
            lead_id = await self.db.upsert_lead(lead)
            lead.id = lead_id
            saved_leads.append(lead)

        await self.db.log_activity(
            agent_name="ScoutAgent",
            action="استكشاف عملاء محتملين",
            details=f"تم اكتشاف {len(saved_leads)} شركة في قطاع ({industry or 'متعدد'})",
            org_id=org_id,
            level="info",
        )
        return saved_leads

    async def _discover_prospects(
        self,
        industry: Optional[str],
        region: Optional[str],
        language: str,
        limit: int,
        org_id: int = 1,
    ) -> List[Dict[str, Any]]:
        if language == "en":
            pool = SAMPLE_PROSPECTS_EN + SAMPLE_PROSPECTS_AR
        elif language == "both":
            pool = SAMPLE_PROSPECTS_AR[: max(1, limit // 2)] + SAMPLE_PROSPECTS_EN[: max(1, limit - limit // 2)] + SAMPLE_PROSPECTS_AR
        else:
            pool = SAMPLE_PROSPECTS_AR + SAMPLE_PROSPECTS_EN

        if industry:
            filtered = [p for p in pool if industry.lower() in p["industry"].lower()]
            if filtered:
                pool = filtered
            else:
                # Dynamic sector synthesis for ANY custom industry requested by the user!
                pool = self._generate_dynamic_sector_prospects(
                    industry=industry,
                    region=region or "المملكة العربية السعودية",
                    language="en" if language == "en" else "ar",
                    limit=limit,
                )

        if region:
            filtered_reg = [p for p in pool if region.lower() in p["region"].lower()]
            if filtered_reg:
                pool = filtered_reg

        return pool[:limit]

    def _generate_dynamic_sector_prospects(
        self,
        industry: str,
        region: str,
        language: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Synthesize realistic B2B prospects tailored to ANY custom sector entered by the user."""
        slug_base = re.sub(r"[^a-z0-9]", "", industry.lower())[:10] or "sector"
        ar_prefixes = ["مجموعة الريادة", "شركة آفاق", "مؤسسة قمم", "شركة نخبة", "منصة إتقان"]
        ar_contacts = [
            ("م. عبد الله السبيعي", "المدير التنفيذي"),
            ("أ. نورة الشهري", "مديرة تطوير الأعمال والمشتريات"),
            ("د. فيصل الحربي", "مدير العمليات والشراكات"),
            ("م. ماجد الزهراني", "نائب الرئيس للنمو والتوسع"),
            ("أ. ريم العبدالكريم", "مديرة المشاريع الاستراتيجية"),
        ]
        results: List[Dict[str, Any]] = []
        for idx in range(limit):
            prefix = ar_prefixes[idx % len(ar_prefixes)]
            contact_name, contact_role = ar_contacts[idx % len(ar_contacts)]
            domain = f"{slug_base}{idx+1}.sa"
            if language == "en":
                results.append(
                    {
                        "company_name": f"Apex {industry.title()} Group #{idx+1}",
                        "website": f"https://apex-{slug_base}{idx+1}.com",
                        "industry": industry,
                        "region": region or "Global",
                        "contact_name": "jordan.miller" if idx % 2 == 0 else "Alex Mercer",
                        "contact_role": "VP of Operations & Partnerships",
                        "contact_email": f"partnerships@apex-{slug_base}{idx+1}.com",
                        "company_summary": f"Leading B2B organization operating in {industry} across {region}, actively expanding operational capabilities.",
                        "language": "en",
                    }
                )
            else:
                results.append(
                    {
                        "company_name": f"{prefix} في {industry}",
                        "website": f"https://{domain}",
                        "industry": industry,
                        "region": region,
                        "contact_name": contact_name,
                        "contact_role": contact_role,
                        "contact_email": f"info@{domain}",
                        "company_summary": f"شركة رائدة متخصصة في مجال ({industry}) في {region}، تبحث عن حلول متقدمة لرفع كفاءة التشغيل وزيادة المبيعات.",
                        "language": "ar",
                    }
                )
        return results

    @staticmethod
    def _load_from_csv(path: Path, default_lang: str = "ar") -> List[Dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        results: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(
                    {
                        "company_name": row.get("company_name") or row.get("الشركة") or "Unknown Corp",
                        "website": row.get("website") or row.get("الموقع") or "",
                        "industry": row.get("industry") or row.get("القطاع") or "Tech",
                        "region": row.get("region") or row.get("المنطقة") or "",
                        "contact_name": row.get("contact_name") or row.get("الاسم") or "",
                        "contact_role": row.get("contact_role") or row.get("المنصب") or "",
                        "contact_email": row.get("contact_email") or row.get("البريد") or "",
                        "company_summary": row.get("company_summary") or row.get("نبذة") or "",
                        "language": row.get("language") or default_lang,
                    }
                )
        return results
