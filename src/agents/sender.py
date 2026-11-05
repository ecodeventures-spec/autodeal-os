"""Sender Agent: Manages outbox queue, daily caps, SaaS quotas, stop-on-reply, and human-like pacing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.base import BaseSalesAgent
from src.core.models import ApprovalStatus, LeadStatus
from src.services.mailer import MailerService


class SenderAgent(BaseSalesAgent):
    """
    Processes approved email drafts from the outbox queue, enforces daily caps,
    SaaS plan quotas, and stop-on-reply rules, and dispatches emails via MailerService.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.mailer = MailerService(self.settings)

    async def run(
        self,
        respect_schedule_time: bool = False,
        pacing_delay_seconds: float = 0.0,
        org_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        sent_today = await self.db.count_sent_today(org_id=org_id)
        daily_cap = self.settings.sender.daily_send_cap
        remaining_quota = max(0, daily_cap - sent_today)

        if remaining_quota == 0:
            return {
                "sent_count": 0,
                "skipped_count": 0,
                "reason": "تم الوصول إلى الحد الأقصى للإرسال اليومي (Daily Cap Reached)",
            }

        approved_drafts = await self.db.list_email_drafts(
            approval_status=ApprovalStatus.APPROVED, org_id=org_id
        )

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sent_count = 0
        skipped_count = 0
        sent_details: List[Dict[str, Any]] = []

        for draft in approved_drafts:
            if sent_count >= remaining_quota:
                break

            if respect_schedule_time and draft.scheduled_at and draft.scheduled_at > now_iso:
                skipped_count += 1
                continue

            lead = await self.db.get_lead(draft.lead_id)
            if not lead or not lead.contact_email:
                skipped_count += 1
                continue

            if draft.step_number < 4 and self.settings.sender.stop_on_reply and lead.status in (
                LeadStatus.REPLIED,
                LeadStatus.MEETING_BOOKED,
                LeadStatus.DO_NOT_CONTACT,
                LeadStatus.CLOSED_LOST,
            ):
                if draft.id:
                    await self.db.update_draft_approval(draft.id, ApprovalStatus.CANCELLED)
                skipped_count += 1
                continue

            if draft.step_number in (2, 3) and not respect_schedule_time:
                skipped_count += 1
                continue

            effective_org = org_id or draft.org_id or lead.org_id or 1
            await self.db.check_and_consume_quota(org_id=effective_org, resource="emails", amount=1)

            delivered = await self.mailer.send_email(
                to_email=lead.contact_email,
                subject=draft.subject,
                body=draft.body,
            )

            if delivered and draft.id:
                await self.db.mark_draft_sent(draft.id)
                if draft.step_number < 4:
                    await self.db.update_lead_status(lead.id, LeadStatus.ACTIVE_CAMPAIGN)
                sent_count += 1
                sent_details.append(
                    {
                        "draft_id": draft.id,
                        "lead_id": lead.id,
                        "company_name": lead.company_name,
                        "to_email": lead.contact_email,
                        "step_number": draft.step_number,
                        "subject": draft.subject,
                        "dry_run": self.settings.system.dry_run,
                    }
                )
                if pacing_delay_seconds > 0:
                    await asyncio.sleep(pacing_delay_seconds)

        return {
            "sent_count": sent_count,
            "skipped_count": skipped_count,
            "sent_today_total": sent_today + sent_count,
            "daily_cap": daily_cap,
            "details": sent_details,
        }
