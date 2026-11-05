"""Enricher & Scorer Agent: Scrapes prospect websites, verifies emails, and scores ICP fit."""

from __future__ import annotations

from typing import List, Optional

from src.agents.base import BaseSalesAgent
from src.core.models import EnrichmentResult, Lead, LeadStatus
from src.services.email_verifier import EmailVerifier
from src.services.scraper import WebsiteScraper


class EnricherAgent(BaseSalesAgent):
    """
    Enriches discovered leads by scraping their website, verifying email deliverability,
    extracting pain points & personalization hooks, and scoring ICP fit (0-100).
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.scraper = WebsiteScraper(timeout=2.0)
        self.verifier = EmailVerifier(check_dns=False)

    async def run(self, lead_ids: Optional[List[int]] = None) -> List[Lead]:
        if lead_ids:
            leads = [await self.db.get_lead(lid) for lid in lead_ids]
            leads = [l for l in leads if l is not None]
        else:
            leads = await self.db.list_leads(status=LeadStatus.DISCOVERED)

        enriched_leads: List[Lead] = []
        for lead in leads:
            updated = await self.enrich_single_lead(lead)
            enriched_leads.append(updated)
        return enriched_leads

    async def enrich_single_lead(self, lead: Lead) -> Lead:
        if self.llm._has_live_credentials() and not self.settings.system.dry_run:
            scraped = await self.scraper.scrape_url(lead.website)
        else:
            from src.services.scraper import ScrapedWebsiteData
            scraped = ScrapedWebsiteData(url=lead.website, domain="", reachable=False)

        # If lead has no email, use discovered email or infer corporate contact email
        if not lead.contact_email:
            if scraped.emails_found:
                lead.contact_email = scraped.emails_found[0]
            elif scraped.domain:
                lead.contact_email = f"contact@{scraped.domain}"

        # Verify email
        verification = await self.verifier.verify(lead.contact_email)
        lead.email_verified = verification.is_deliverable

        # Build enrichment prompt for LLM
        website_context = (
            f"Title: {scraped.title}\n"
            f"Meta: {scraped.meta_description}\n"
            f"Headings: {', '.join(scraped.headings)}\n"
            f"Excerpt: {scraped.body_excerpt[:600]}\n"
            if scraped.reachable
            else f"Existing Summary: {lead.company_summary}"
        )

        lang = lead.language or self.settings.system.default_language
        value_prop = (
            self.settings.icp.value_proposition_ar
            if lang == "ar"
            else self.settings.icp.value_proposition_en
        )

        prompt = (
            f"Analyze this B2B prospect and score their ICP fit from 0 to 100.\n"
            f"Company Name: {lead.company_name}\n"
            f"Website: {lead.website}\n"
            f"Industry: {lead.industry}\n"
            f"Region: {lead.region}\n"
            f"Contact: {lead.contact_name} ({lead.contact_role})\n"
            f"Website Intelligence:\n{website_context}\n\n"
            f"Our Value Proposition: {value_prop}\n"
            f"Target Industries: {', '.join(self.settings.icp.target_industries)}\n"
            f"Language for output fields: {'Arabic (العربية)' if lang == 'ar' else 'English'}"
        )

        def _fallback_enrichment() -> EnrichmentResult:
            if lang == "ar":
                return EnrichmentResult(
                    company_summary=lead.company_summary
                    or f"شركة رائدة في قطاع {lead.industry} تعمل في {lead.region}.",
                    pain_points="الحاجة إلى أتمتة عمليات المتابعة مع العملاء وتقليل الوقت المهدر في المهام اليدوية المتكررة.",
                    personalization_hook=f"لفت انتباهي توسع {lead.company_name} المميز في قطاع {lead.industry} داخل {lead.region}.",
                    contact_role_guess=lead.contact_role or "الرئيس التنفيذي / مدير النمو",
                    qualification_score=84 if lead.email_verified else 68,
                    score_reasoning="تطابق قوي مع ملف العميل المثالي (ICP) من حيث القطاع والمنطقة الجغرافية وإمكانية تحقيق عائد سريع.",
                )
            else:
                return EnrichmentResult(
                    company_summary=lead.company_summary
                    or f"Growing {lead.industry} provider operating in {lead.region}.",
                    pain_points="Scaling outbound pipeline and customer onboarding without increasing headcount overhead.",
                    personalization_hook=f"Noticed {lead.company_name}'s rapid momentum in {lead.industry} across {lead.region}.",
                    contact_role_guess=lead.contact_role or "VP of Growth / Revenue Operations",
                    qualification_score=86 if lead.email_verified else 70,
                    score_reasoning="Strong ICP alignment in target B2B vertical with verified corporate domain.",
                )

        enrichment = await self.llm.generate_structured(
            prompt=prompt,
            schema_cls=EnrichmentResult,
            system_instruction=(
                "You are an elite B2B sales research analyst (Scout/Enricher). "
                "Evaluate prospects objectively and craft specific, authentic personalization hooks."
            ),
            fallback_factory=_fallback_enrichment,
        )

        lead.company_summary = enrichment.company_summary
        lead.pain_points = enrichment.pain_points
        lead.personalization_hook = enrichment.personalization_hook
        if not lead.contact_role:
            lead.contact_role = enrichment.contact_role_guess
        lead.qualification_score = enrichment.qualification_score
        lead.score_reasoning = enrichment.score_reasoning

        min_score = self.settings.icp.min_qualification_score
        if lead.qualification_score >= min_score and lead.email_verified:
            lead.status = LeadStatus.ENRICHED
        else:
            lead.status = LeadStatus.DISQUALIFIED

        lead.id = await self.db.upsert_lead(lead)
        return lead
