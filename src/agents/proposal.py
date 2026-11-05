"""Proposal Agent: Converts Discovery Call transcripts into tailored Interactive B2B Proposals & Follow-up Drafts."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.agents.base import BaseSalesAgent
from src.core.models import ApprovalStatus, EmailDraft, LeadStatus, PlanTier
from src.services.proposals_bridge import ProposalsBridgeService


class ProposalAgent(BaseSalesAgent):
    """
    Universal bridge between Outbound Discovery and Deal Closing.
    Processes Zoom/Meet transcripts or notes, reads the tenant's CompanyProfile & Services Catalog,
    creates a persistent InteractiveProposal accessible at `/c/{slug}`,
    and drafts the official Proposal Delivery Email into the Approval Ladder.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.bridge = ProposalsBridgeService(self.settings, self.llm)

    async def run(
        self,
        lead_id: int,
        transcript_text: str,
        custom_notes: str = "",
        org_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate tailored interactive proposal and follow-up draft for a specific lead."""
        lead = await self.db.get_lead(lead_id, org_id=org_id)
        if not lead:
            raise ValueError(f"Lead ID {lead_id} not found in database.")

        effective_org_id = org_id or lead.org_id or 1

        # 1. Check and consume SaaS Proposal Quota
        org = await self.db.check_and_consume_quota(
            org_id=effective_org_id, resource="proposals", amount=1
        )
        white_label = org.plan_tier == PlanTier.BUSINESS.value

        # 2. Fetch tenant's Company Profile & Services Catalog
        tenant_settings = await self.db.get_tenant_settings(effective_org_id)
        tenant_profile = tenant_settings.get("company_profile") or {}
        provider_name = (
            tenant_profile.get("company_name_ar") or self.settings.company.company_name_ar
        )

        # 3. Run AI Transcript Analysis & Interactive Proposal Creation
        result = await self.bridge.analyze_transcript_and_create_proposal(
            lead=lead,
            transcript_text=transcript_text,
            custom_notes=custom_notes,
            tenant_profile=tenant_profile,
            white_label=white_label,
        )

        interactive_proposal = result["interactive_proposal"]
        proposal_id = await self.db.save_proposal(interactive_proposal)
        interactive_proposal.id = proposal_id

        proposal_url = result["proposal_urls"]["local_url"]
        spec = result["spec"]

        # 4. Update Lead Record with Proposal Link and Status
        lead.proposal_status = "generated"
        lead.proposal_url = proposal_url
        lead.status = LeadStatus.MEETING_BOOKED
        await self.db.upsert_lead(lead)

        # 5. Create Follow-up Email Draft in the Approval Ladder (Step 4 / Proposal Delivery)
        draft = EmailDraft(
            org_id=effective_org_id,
            lead_id=lead_id,
            campaign_id=lead.campaign_id or 1,
            step_number=4,
            subject=spec.get(
                "follow_up_email_subject",
                f"العرض الفني والمالي لشركة {lead.company_name} | {provider_name}",
            ),
            body=spec.get("follow_up_email_body", ""),
            word_count=len(spec.get("follow_up_email_body", "").split()),
            language=lead.language or "ar",
            approval_status=ApprovalStatus.PENDING,
        )
        draft_ids = await self.db.save_email_drafts([draft])
        draft.id = draft_ids[0] if draft_ids else None

        await self.db.log_activity(
            agent_name="ProposalAgent",
            action="توليد عرض فني ومالي تفاعلي",
            details=f"تم إصدار العرض التفاعلي لشركة {lead.company_name} على الرابط {proposal_url}",
            org_id=effective_org_id,
            level="success",
        )

        result["follow_up_draft"] = draft.model_dump()
        result["proposal"] = interactive_proposal.model_dump()
        result["lead"] = lead.model_dump()
        return result
