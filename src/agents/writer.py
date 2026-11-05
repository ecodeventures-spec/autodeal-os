"""Writer Agent: Crafts hyper-personalized 3-step cold email sequences tailored to the tenant company's actual business & value proposition."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import List, Optional

from src.agents.base import BaseSalesAgent
from src.core.config import BASE_DIR
from src.core.models import (
    ApprovalStatus,
    EmailDraft,
    GeneratedSequenceSchema,
    Lead,
    LeadStatus,
    SequenceStepSchema,
)


class WriterAgent(BaseSalesAgent):
    """
    Generates a 3-email sequence for each qualified (`ENRICHED`) lead,
    dynamically injecting the tenant company's identity and value proposition,
    enforces anti-AI buzzword filtering and strict word-count caps,
    and routes drafts into the Approval Ladder.
    """

    async def run(
        self, lead_ids: Optional[List[int]] = None, org_id: Optional[int] = None
    ) -> List[EmailDraft]:
        if lead_ids:
            leads = [await self.db.get_lead(lid, org_id=org_id) for lid in lead_ids]
            leads = [l for l in leads if l is not None]
        else:
            leads = await self.db.list_leads(status=LeadStatus.ENRICHED, org_id=org_id)

        all_drafts: List[EmailDraft] = []
        for lead in leads:
            drafts = await self.write_sequence_for_lead(lead)
            all_drafts.extend(drafts)
        return all_drafts

    async def write_sequence_for_lead(self, lead: Lead) -> List[EmailDraft]:
        org_id = lead.org_id or 1
        tenant_cfg = await self.db.get_tenant_settings(org_id)
        cp = tenant_cfg.get("company_profile", {})
        icp_cfg = tenant_cfg.get("icp", {})
        sender_cfg = tenant_cfg.get("sender", {})

        lang = (lead.language or self.settings.system.default_language).lower()
        system_prompt = self._load_writer_prompt(lang)

        our_company_ar = cp.get("company_name_ar") or self.settings.company.company_name_ar
        our_company_en = cp.get("company_name_en") or self.settings.company.company_name_en
        our_industry = cp.get("industry") or self.settings.company.industry

        value_prop = (
            cp.get("value_proposition_ar")
            or icp_cfg.get("value_proposition_ar")
            or self.settings.icp.value_proposition_ar
            if lang == "ar"
            else cp.get("value_proposition_en")
            or icp_cfg.get("value_proposition_en")
            or self.settings.icp.value_proposition_en
        )
        sender_persona = (
            cp.get("sender_persona_ar")
            or icp_cfg.get("sender_persona_ar")
            or self.settings.icp.sender_persona_ar
            if lang == "ar"
            else cp.get("sender_persona_en")
            or icp_cfg.get("sender_persona_en")
            or self.settings.icp.sender_persona_en
        )
        sender_name = sender_cfg.get("sender_name") or self.settings.sender.sender_name
        booking_link = (
            sender_cfg.get("calendar_booking_link") or self.settings.sender.calendar_booking_link
        )

        prompt = (
            f"Create a 3-step outbound email sequence for this prospect:\n"
            f"- Prospect Company: {lead.company_name}\n"
            f"- Prospect Industry: {lead.industry}\n"
            f"- Contact Name: {lead.contact_name}\n"
            f"- Contact Role: {lead.contact_role}\n"
            f"- Company Summary: {lead.company_summary}\n"
            f"- Pain Points: {lead.pain_points}\n"
            f"- Personalization Hook: {lead.personalization_hook}\n"
            f"- Our Company: {our_company_ar if lang == 'ar' else our_company_en} ({our_industry})\n"
            f"- Our Value Proposition: {value_prop}\n"
            f"- Sender Persona: {sender_persona} ({sender_name})\n"
            f"- Booking Link: {booking_link}\n"
            f"- Max Words: Step 1 <= {self.settings.writer.max_words_step_1}, "
            f"Step 2 <= {self.settings.writer.max_words_step_2}, "
            f"Step 3 <= {self.settings.writer.max_words_step_3}\n"
        )

        def _fallback_sequence() -> GeneratedSequenceSchema:
            if lang == "ar":
                first_name = lead.contact_name or "فريق الإدارة"
                hook = lead.personalization_hook or f"تابعنا التوسع المميز لشركة {lead.company_name} في قطاع {lead.industry}."
                return GeneratedSequenceSchema(
                    steps=[
                        SequenceStepSchema(
                            step_number=1,
                            subject=f"تعاون مشترك لتسريع نمو {lead.company_name} | {our_company_ar}",
                            body=(
                                f"مرحباً {first_name}،\n\n"
                                f"{hook}\n\n"
                                f"{value_prop}\n\n"
                                f"هل يناسبك اتصال سريع لمدة 10 دقائق هذا الأسبوع لاستعراض كيف يمكن لـ ({our_company_ar}) دعم أهدافكم؟\n\n"
                                f"تحياتي،\n{sender_name}\n{sender_persona}"
                            ),
                        ),
                        SequenceStepSchema(
                            step_number=2,
                            subject=f"متابعة سريعة: {lead.company_name} × {our_company_ar}",
                            body=(
                                f"مرحباً {first_name}،\n\n"
                                f"أردت المتابعة سريعاً حول رسالتي السابقة بخصوص حلول ({our_industry}) لشركة {lead.company_name}.\n\n"
                                f"هل ترغب في الاطلاع على عرض فني ومالي مخصص يناسب احتياجاتكم الحالية؟\n\n"
                                f"{sender_name}"
                            ),
                        ),
                        SequenceStepSchema(
                            step_number=3,
                            subject=f"سؤال أخير - {lead.company_name}",
                            body=(
                                f"مرحباً {first_name}،\n\n"
                                f"أعلم أن جدولك مزدحم. هل تطوير ({our_industry}) ضمن أولوياتكم للربع الحالي، "
                                f"أم تفضل أن نتواصل في وقت لاحق؟\n\n"
                                f"شكراً لك،\n{sender_name}"
                            ),
                        ),
                    ]
                )
            else:
                first_name = (lead.contact_name or "there").split()[0]
                hook = lead.personalization_hook or f"Noticed {lead.company_name}'s strong momentum in {lead.industry}."
                return GeneratedSequenceSchema(
                    steps=[
                        SequenceStepSchema(
                            step_number=1,
                            subject=f"Quick idea for {lead.company_name} | {our_company_en}",
                            body=(
                                f"Hi {first_name},\n\n"
                                f"{hook}\n\n"
                                f"{value_prop}\n\n"
                                f"Open to a 10-minute walkthrough this week?\n\n"
                                f"Best,\n{sender_name}\n{sender_persona}"
                            ),
                        ),
                        SequenceStepSchema(
                            step_number=2,
                            subject=f"Re: {lead.company_name} × {our_company_en}",
                            body=(
                                f"Hi {first_name},\n\n"
                                f"Quick follow-up regarding our {our_industry} solutions for {lead.company_name}.\n\n"
                                f"Worth a quick look at a tailored proposal?\n\n"
                                f"Best,\n{sender_name}"
                            ),
                        ),
                        SequenceStepSchema(
                            step_number=3,
                            subject=f"Should I close the loop, {first_name}?",
                            body=(
                                f"Hi {first_name},\n\n"
                                f"Is upgrading your {our_industry} operations a priority for {lead.company_name} this quarter, "
                                f"or should I check back later?\n\n"
                                f"Thanks,\n{sender_name}"
                            ),
                        ),
                    ]
                )

        generated = await self.llm.generate_structured(
            prompt=prompt,
            schema_cls=GeneratedSequenceSchema,
            system_instruction=system_prompt,
            fallback_factory=_fallback_sequence,
        )

        now = datetime.now(timezone.utc)
        delays = self.settings.writer.step_delays_days or [0, 3, 7]
        initial_approval = (
            ApprovalStatus.APPROVED
            if self.settings.system.auto_approve_sequences
            else ApprovalStatus.PENDING
        )

        drafts: List[EmailDraft] = []
        for idx, step in enumerate(generated.steps[:3]):
            step_num = idx + 1
            cleaned_body = self.sanitize_copy(step.body, lang=lang, step_number=step_num)
            delay_days = delays[idx] if idx < len(delays) else idx * 3
            scheduled_dt = (now + timedelta(days=delay_days)).isoformat(timespec="seconds")

            draft = EmailDraft(
                org_id=org_id,
                lead_id=int(lead.id or 0),
                campaign_id=lead.campaign_id or 1,
                step_number=step_num,
                subject=step.subject.strip(),
                body=cleaned_body,
                word_count=len(cleaned_body.split()),
                language=lang,
                approval_status=initial_approval,
                scheduled_at=scheduled_dt,
            )
            drafts.append(draft)

        saved_ids = await self.db.save_email_drafts(drafts)
        for d, did in zip(drafts, saved_ids):
            d.id = did

        new_lead_status = (
            LeadStatus.APPROVED
            if self.settings.system.auto_approve_sequences
            else LeadStatus.SEQUENCE_DRAFTED
        )
        if lead.id:
            await self.db.update_lead_status(lead.id, new_lead_status)

        return drafts

    def sanitize_copy(self, text: str, lang: str, step_number: int) -> str:
        """Remove banned AI buzzwords and enforce word count limits."""
        cleaned = text.strip()
        banned_list = (
            self.settings.writer.banned_buzzwords_ar
            if lang == "ar"
            else self.settings.writer.banned_buzzwords_en
        )
        for phrase in banned_list:
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            cleaned = pattern.sub("", cleaned)

        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        max_words = {
            1: self.settings.writer.max_words_step_1,
            2: self.settings.writer.max_words_step_2,
            3: self.settings.writer.max_words_step_3,
        }.get(step_number, 75)

        words = cleaned.split()
        if len(words) > max_words + 15:
            cleaned = " ".join(words[:max_words]) + "..."

        return cleaned

    @staticmethod
    def _load_writer_prompt(lang: str) -> str:
        filename = "writer_ar.txt" if lang == "ar" else "writer_en.txt"
        path: Path = BASE_DIR / "config" / "prompts" / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return "You are an expert B2B outbound copywriter."
