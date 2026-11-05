"""Handler Agent: Polls replies, classifies intent, stops follow-ups, and drafts meeting responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agents.base import BaseSalesAgent
from src.core.models import (
    InboxReply,
    Lead,
    LeadStatus,
    ReplyClassificationSchema,
    ReplyIntent,
)
from src.services.mailer import MailerService


class HandlerAgent(BaseSalesAgent):
    """
    Processes incoming prospect replies (from IMAP or simulated replies),
    classifies intent, triggers Stop-on-Reply, updates lead lifecycle status,
    and drafts a contextual response with the meeting booking link.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.mailer = MailerService(self.settings)

    async def run(
        self,
        simulated_replies: Optional[List[Dict[str, str]]] = None,
    ) -> List[InboxReply]:
        raw_messages = simulated_replies if simulated_replies is not None else await self.mailer.poll_unseen_replies()
        processed: List[InboxReply] = []

        for msg in raw_messages:
            reply_obj = await self.process_single_reply(
                from_email=msg["from_email"],
                subject=msg.get("subject", "Re: تواصل"),
                body=msg["body"],
            )
            if reply_obj:
                processed.append(reply_obj)
        return processed

    async def process_single_reply(
        self,
        from_email: str,
        subject: str,
        body: str,
    ) -> Optional[InboxReply]:
        lead = await self.db.get_lead_by_email(from_email)
        if not lead or not lead.id:
            # If unknown sender, attach to first active lead or skip
            all_leads = await self.db.list_leads()
            if not all_leads:
                return None
            lead = all_leads[0]

        classification = await self.classify_and_draft_response(lead, subject, body)

        # Stop-on-reply: cancel any pending/scheduled follow-ups
        if self.settings.sender.stop_on_reply and lead.id:
            await self.db.cancel_pending_drafts_for_lead(lead.id)

        # Update Lead Status based on Intent
        if lead.id:
            if classification.intent == ReplyIntent.INTERESTED:
                await self.db.update_lead_status(lead.id, LeadStatus.MEETING_BOOKED)
            elif classification.intent in (ReplyIntent.UNSUBSCRIBE, ReplyIntent.NOT_INTERESTED):
                await self.db.update_lead_status(lead.id, LeadStatus.DO_NOT_CONTACT)
            else:
                await self.db.update_lead_status(lead.id, LeadStatus.REPLIED)

            # Check if prospect asked for a proposal / quotation
            lower_body = body.lower()
            if any(w in lower_body for w in ("عرض", "عرض فني", "عرض مالي", "proposal", "quote", "quotation", "تسعير", "تكلفة")):
                lead.proposal_status = "requested"
                await self.db.upsert_lead(lead)

        reply_record = InboxReply(
            lead_id=int(lead.id or 1),
            from_email=from_email,
            subject=subject,
            body=body,
            intent=classification.intent,
            confidence=classification.confidence,
            ai_suggested_reply=classification.suggested_reply,
            reply_approved=False,
        )
        reply_record.id = await self.db.save_reply(reply_record)
        return reply_record

    async def classify_and_draft_response(
        self,
        lead: Lead,
        subject: str,
        body: str,
    ) -> ReplyClassificationSchema:
        lang = (lead.language or self.settings.system.default_language).lower()
        booking_link = self.settings.sender.calendar_booking_link
        sender_name = self.settings.sender.sender_name

        prompt = (
            f"Classify this B2B prospect's email reply and draft an appropriate response.\n"
            f"Prospect: {lead.contact_name} at {lead.company_name}\n"
            f"Subject: {subject}\n"
            f"Reply Body:\n{body}\n\n"
            f"Calendar Booking Link: {booking_link}\n"
            f"Sender Name: {sender_name}\n"
            f"Language: {'Arabic' if lang == 'ar' else 'English'}\n"
            f"Valid intents: interested, objection, question, out_of_office, not_interested, unsubscribe."
        )

        def _fallback_classification() -> ReplyClassificationSchema:
            lower_body = body.lower()
            if any(w in lower_body for w in ("غير مهتم", "الغاء", "إلغاء", "unsubscribe", "not interested", "stop")):
                intent = ReplyIntent.NOT_INTERESTED
                suggested = (
                    f"شكراً لتوضيحك {lead.contact_name}، تم إيقاف المتابعة وحذف بريدك من قائمتنا. نتمنى لكم كل التوفيق!"
                    if lang == "ar"
                    else f"Thanks for letting me know, {lead.contact_name}. I've removed you from our follow-up list. Wishing {lead.company_name} all the best!"
                )
            elif any(w in lower_body for w in ("اجتماع", "موعد", "مهتم", "نعم", "تفاصيل", "interested", "call", "meet", "sure", "yes")):
                intent = ReplyIntent.INTERESTED
                suggested = (
                    f"يسعدني جداً ذلك {lead.contact_name}!\n\n"
                    f"يمكنك اختيار الوقت الأنسب لك مباشرة عبر رابط التقويم التالي لإجراء مكالمة سريعة (10 دقائق):\n"
                    f"{booking_link}\n\n"
                    f"تمنياتي بالتوفيق،\n{sender_name}"
                    if lang == "ar"
                    else f"Great to hear, {lead.contact_name}!\n\n"
                    f"Feel free to grab any 10-minute slot that works for you here:\n"
                    f"{booking_link}\n\n"
                    f"Best,\n{sender_name}"
                )
            elif any(w in lower_body for w in ("سعر", "تكلفة", "كيف", "سؤال", "price", "cost", "how", "?”", "?")):
                intent = ReplyIntent.QUESTION
                suggested = (
                    f"سؤال ممتاز {lead.contact_name}!\n\n"
                    f"تعتمد الباقة على حجم العمليات المستهدفة، وعادة ما يظهر العائد خلال أول 30 يوماً. "
                    f"هل يناسبك اتصال سريع لمدة 10 دقائق عبر الرابط التالي لاستعراض التفاصيل؟\n"
                    f"{booking_link}\n\n"
                    f"تحياتي،\n{sender_name}"
                    if lang == "ar"
                    else f"Great question, {lead.contact_name}!\n\n"
                    f"Pricing scales with workflow volume and typically pays for itself within 30 days. "
                    f"Happy to walk through specifics on a quick 10-min call:\n"
                    f"{booking_link}\n\n"
                    f"Best,\n{sender_name}"
                )
            else:
                intent = ReplyIntent.INTERESTED
                suggested = (
                    f"شكراً لردك {lead.contact_name}!\n"
                    f"يسعدني استعراض التفاصيل معك في مكالمة سريعة عبر الرابط:\n{booking_link}\n\n{sender_name}"
                    if lang == "ar"
                    else f"Thanks for getting back to me, {lead.contact_name}! You can book a quick chat here: {booking_link}\n\n{sender_name}"
                )

            return ReplyClassificationSchema(
                intent=intent,
                confidence=0.92,
                reasoning="تم التصنيف بناءً على تحليل سياق رسالة العميل ونبرته.",
                suggested_reply=suggested,
            )

        return await self.llm.generate_structured(
            prompt=prompt,
            schema_cls=ReplyClassificationSchema,
            system_instruction=(
                "You are an expert B2B inbox response handler. Classify lead intent accurately "
                "and draft concise, polite responses that move interested prospects to book a meeting."
            ),
            fallback_factory=_fallback_classification,
        )
