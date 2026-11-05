"""Core Orchestrator: Coordinates all 8 AI Sub-Agents, Multi-Tenant SaaS Pipeline, and System Health."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agents.analyst import AnalystAgent
from src.agents.company_profiler import CompanyProfilerAgent
from src.agents.enricher import EnricherAgent
from src.agents.handler import HandlerAgent
from src.agents.proposal import ProposalAgent
from src.agents.scout import ScoutAgent
from src.agents.sender import SenderAgent
from src.agents.writer import WriterAgent
from src.core.config import AppSettings, load_settings
from src.core.database import DatabaseManager
from src.core.llm import UnifiedLLMClient
from src.core.models import ApprovalStatus, LeadStatus
from src.services.exporter import CampaignExporter


class SalesOrchestrator:
    """Central coordinator managing the end-to-end outbound sales & proposals SaaS pipeline."""

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()
        self.db = DatabaseManager(self.settings.database_path)
        self.llm = UnifiedLLMClient(self.settings)

        self.company_profiler = CompanyProfilerAgent(self.settings, self.db, self.llm)
        self.scout = ScoutAgent(self.settings, self.db, self.llm)
        self.enricher = EnricherAgent(self.settings, self.db, self.llm)
        self.writer = WriterAgent(self.settings, self.db, self.llm)
        self.sender = SenderAgent(self.settings, self.db, self.llm)
        self.handler = HandlerAgent(self.settings, self.db, self.llm)
        self.analyst = AnalystAgent(self.settings, self.db, self.llm)
        self.proposal = ProposalAgent(self.settings, self.db, self.llm)
        self.exporter = CampaignExporter(self.db)

    async def initialize(self) -> None:
        await self.db.initialize()

    def refresh_llm_clients(self) -> None:
        self.llm = UnifiedLLMClient(self.settings)
        for agent in (
            self.company_profiler,
            self.scout,
            self.enricher,
            self.writer,
            self.sender,
            self.handler,
            self.analyst,
            self.proposal,
        ):
            agent.llm = self.llm
        self.proposal.bridge.llm = self.llm

    async def run_full_pipeline(
        self,
        language: str = "ar",
        limit: int = 4,
        auto_approve: bool = False,
        industry: Optional[str] = None,
        region: Optional[str] = None,
        org_id: int = 1,
    ) -> Dict[str, Any]:
        """
        Execute the full pipeline for a tenant (`org_id`):
        1. Scout discovers prospects
        2. Enricher verifies emails & scores ICP fit
        3. Writer drafts 3-step email sequences tailored to the company profile
        4. Optional Approval & Sender dispatch
        5. Analyst summarizes performance
        """
        await self.initialize()
        discovered = await self.scout.run(
            industry=industry,
            region=region,
            language=language,
            limit=limit,
            org_id=org_id,
        )
        discovered_ids = [int(l.id) for l in discovered if l.id is not None]

        enriched = await self.enricher.run(lead_ids=discovered_ids)
        qualified_ids = [
            int(l.id)
            for l in enriched
            if l.id is not None and l.status == LeadStatus.ENRICHED
        ]

        drafts = await self.writer.run(lead_ids=qualified_ids, org_id=org_id)

        send_summary: Dict[str, Any] = {"sent_count": 0, "skipped_count": 0}
        if auto_approve or self.settings.system.auto_approve_sequences:
            await self.approve_all_pending(org_id=org_id)
            send_summary = await self.sender.run(org_id=org_id)

        analytics = await self.analyst.run(org_id=org_id)
        await self.db.log_activity(
            agent_name="Orchestrator",
            action="تشغيل دورة المبيعات الكاملة",
            details=f"اكتشاف {len(discovered)}، تأهيل {len(qualified_ids)}، وصياغة {len(drafts)} رسالة",
            org_id=org_id,
            level="success",
        )
        return {
            "discovered_count": len(discovered),
            "qualified_count": len(qualified_ids),
            "drafts_created": len(drafts),
            "send_summary": send_summary,
            "analytics": analytics,
        }

    async def approve_all_pending(self, org_id: Optional[int] = None) -> int:
        pending = await self.db.list_email_drafts(
            approval_status=ApprovalStatus.PENDING, org_id=org_id
        )
        lead_ids_updated = set()
        for draft in pending:
            if draft.id:
                await self.db.update_draft_approval(draft.id, ApprovalStatus.APPROVED)
                lead_ids_updated.add(draft.lead_id)
        for lid in lead_ids_updated:
            await self.db.update_lead_status(lid, LeadStatus.APPROVED)
        return len(pending)

    async def generate_proposal_for_lead(
        self,
        lead_id: int,
        transcript_text: str,
        custom_notes: str = "",
        org_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Convert a Discovery Call transcript into an Interactive Proposal and follow-up draft."""
        await self.initialize()
        return await self.proposal.run(
            lead_id=lead_id,
            transcript_text=transcript_text,
            custom_notes=custom_notes,
            org_id=org_id,
        )

    async def get_system_health(self, org_id: int = 1) -> Dict[str, Any]:
        """Compute System Readiness Checklist for non-technical users."""
        tenant_cfg = await self.db.get_tenant_settings(org_id)
        cp = tenant_cfg.get("company_profile") or {}
        sender_cfg = tenant_cfg.get("sender") or {}

        has_live_ai = self.llm._has_live_credentials()
        has_smtp = bool(
            (sender_cfg.get("smtp_username") or self.settings.sender.smtp_username)
            and (sender_cfg.get("smtp_password") or self.settings.sender.smtp_password)
        )
        has_company_profile = bool(cp.get("company_name_ar") and cp.get("industry"))
        has_services = bool(cp.get("services_catalog") and len(cp.get("services_catalog", [])) > 0)

        return {
            "ai_engine": {
                "ready": True,
                "mode": "live" if has_live_ai else "smart_simulation",
                "provider": self.settings.llm.provider,
                "model": self.settings.llm.model,
                "label_ar": (
                    f"متصل فعلياً ({self.settings.llm.provider.upper()})"
                    if has_live_ai
                    else "وضع المحاكاة الذكي جاهز (أضف مفتاح API للتشغيل السحابي)"
                ),
            },
            "email_server": {
                "ready": True,
                "mode": "live_smtp" if (has_smtp and not self.settings.system.dry_run) else "dry_run_safe",
                "label_ar": (
                    "خادم البريد SMTP/IMAP متصل وجاهز للإرسال الفعلي"
                    if (has_smtp and not self.settings.system.dry_run)
                    else "وضع الأمان التجريبي (Dry-Run) مفعّل لحماية النطاق"
                ),
            },
            "company_identity": {
                "ready": has_company_profile and has_services,
                "company_name": cp.get("company_name_ar", ""),
                "industry": cp.get("industry", ""),
                "services_count": len(cp.get("services_catalog", [])),
                "label_ar": (
                    f"هوية ({cp.get('company_name_ar')}) مكتملة مع {len(cp.get('services_catalog', []))} باقات"
                    if has_company_profile
                    else "يرجى استكمال تعريف هوية الشركة"
                ),
            },
            "autopilot": {
                "enabled": self.settings.system.autopilot_enabled,
                "interval_minutes": self.settings.system.autopilot_interval_minutes,
            },
        }
