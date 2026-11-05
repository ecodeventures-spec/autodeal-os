"""Unified FastAPI Gateway & Multi-Tenant SaaS Server for NUDHUJ AutoDeal OS (autodeal.nudhuj.com)."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.core.auth import create_access_token, verify_access_token
from src.core.config import BASE_DIR, load_settings, save_settings
from src.core.database import QuotaExceededError
from src.core.models import ApprovalStatus, Lead, LeadStatus, PLAN_DEFINITIONS
from src.core.orchestrator import SalesOrchestrator
from src.services.diagnostics import test_ai_engine_connection, test_email_connections
from src.services.scheduler import AutopilotScheduler

app = FastAPI(
    title="NUDHUJ AutoDeal OS — Autonomous B2B Revenue & Proposals SaaS Platform",
    version="3.0.0",
    description="Unified Multi-Tenant AI Outbound Sales & Turnkey Interactive Proposals Platform (autodeal.nudhuj.com)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ASSETS_DIR = BASE_DIR / "src" / "ui" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

orchestrator = SalesOrchestrator(load_settings())
scheduler = AutopilotScheduler(orchestrator)


def get_current_org_id(request: Request) -> int:
    """Extract tenant org_id from Bearer token if present; default to Org #1 for demo/CLI."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        payload = verify_access_token(token)
        if payload and payload.get("org_id"):
            return int(payload["org_id"])
    return 1


def get_current_user_payload(request: Request) -> Optional[Dict[str, Any]]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        return verify_access_token(token)
    return None


# ==========================================
# Request Schemas
# ==========================================
class RegisterRequest(BaseModel):
    company_name: str
    full_name: str
    email: str
    password: str
    industry: str = "التقنية وحلول الأعمال (B2B)"
    website: str = ""
    plan_tier: str = "free"


class LoginRequest(BaseModel):
    email: str
    password: str


class UpgradePlanRequest(BaseModel):
    plan_tier: str
    billing_cycle: str = "monthly"


class SuperAdminUpgradeRequest(BaseModel):
    org_id: int
    plan_tier: str


class CompanyProfileAnalyzeRequest(BaseModel):
    website_url: str = ""
    raw_profile_text: str = ""
    company_name_hint: str = ""
    industry_hint: str = ""


class CompanyProfileSaveRequest(BaseModel):
    company_profile: Dict[str, Any]


class RunPipelineRequest(BaseModel):
    language: str = "ar"
    limit: int = 4
    auto_approve: bool = False
    industry: Optional[str] = None
    region: Optional[str] = None


class ScoutRequest(BaseModel):
    industry: Optional[str] = None
    region: Optional[str] = None
    language: str = "ar"
    limit: int = 4


class CreateLeadRequest(BaseModel):
    company_name: str
    website: str = ""
    industry: str = "SaaS & Tech"
    region: str = "المملكة العربية السعودية"
    contact_name: str = ""
    contact_role: str = ""
    contact_email: str
    company_summary: str = ""
    language: str = "ar"


class DraftActionRequest(BaseModel):
    action: str
    subject: Optional[str] = None
    body: Optional[str] = None


class SimulateReplyRequest(BaseModel):
    from_email: str
    subject: str = "Re: استفسار حول خدماتكم"
    body: str


class GenerateProposalRequest(BaseModel):
    lead_id: int
    transcript_text: str
    custom_notes: str = ""


class AcceptProposalRequest(BaseModel):
    accepted_by: str


class EmailDiagnosticsRequest(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""


class AutopilotToggleRequest(BaseModel):
    enabled: bool


class SettingsUpdateRequest(BaseModel):
    dry_run: Optional[bool] = None
    auto_approve_sequences: Optional[bool] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    calendar_booking_link: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    daily_send_cap: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    sending_window_start_hour: Optional[int] = None
    sending_window_end_hour: Optional[int] = None
    min_qualification_score: Optional[int] = None
    max_words_step_1: Optional[int] = None
    banned_buzzwords_ar: Optional[List[str]] = None
    banned_buzzwords_en: Optional[List[str]] = None
    value_proposition_ar: Optional[str] = None
    value_proposition_en: Optional[str] = None


@app.on_event("startup")
async def startup_event() -> None:
    await orchestrator.initialize()
    existing_leads = await orchestrator.db.list_leads(org_id=1)
    if not existing_leads:
        await orchestrator.run_full_pipeline(language="both", limit=4, auto_approve=False, org_id=1)
    scheduler.start()


# ==========================================
# Unified Web Pages (Single Domain Routing)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def serve_landing_page() -> HTMLResponse:
    """Serve the SaaS Marketing Website, 7-Stage Product Tour, Pricing & Auth."""
    landing_path = BASE_DIR / "src" / "ui" / "dashboard" / "landing.html"
    if landing_path.exists():
        return HTMLResponse(content=landing_path.read_text(encoding="utf-8"))
    return await serve_dashboard()


@app.get("/app", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard() -> HTMLResponse:
    """Serve the Unified SaaS Dashboard & Control Center."""
    html_path = BASE_DIR / "src" / "ui" / "dashboard" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Dashboard file not found</h1>", status_code=404)
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/c/{slug}", response_class=HTMLResponse)
@app.get("/p/{slug}", response_class=HTMLResponse)
@app.get("/proposal/{slug}", response_class=HTMLResponse)
async def serve_interactive_proposal_viewer(slug: str) -> HTMLResponse:
    """Serve the Unified Client Interactive Proposal Showcase on the same domain."""
    viewer_path = BASE_DIR / "src" / "ui" / "dashboard" / "proposal_viewer.html"
    if not viewer_path.exists():
        return HTMLResponse("<h1>Proposal viewer not found</h1>", status_code=404)
    return HTMLResponse(content=viewer_path.read_text(encoding="utf-8"))


# ==========================================
# SaaS Authentication & Multi-Tenancy APIs
# ==========================================
@app.post("/api/auth/register")
async def api_register(req: RegisterRequest) -> Dict[str, Any]:
    await orchestrator.initialize()
    try:
        org, user = await orchestrator.db.register_tenant_and_user(
            company_name=req.company_name,
            full_name=req.full_name,
            email=req.email,
            password=req.password,
            industry=req.industry,
            website=req.website,
            plan_tier=req.plan_tier,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Automatically run Company Profiler for the new tenant if website or industry was provided
    await orchestrator.company_profiler.run(
        website_url=req.website,
        company_name_hint=req.company_name,
        industry_hint=req.industry,
        org_id=int(org.id or 1),
    )

    token = create_access_token(
        user_id=int(user.id or 1),
        org_id=int(org.id or 1),
        email=user.email,
        role=user.role,
    )
    return {
        "status": "success",
        "access_token": token,
        "user": user.model_dump(),
        "organization": org.model_dump(),
    }


@app.post("/api/auth/login")
async def api_login(req: LoginRequest) -> Dict[str, Any]:
    await orchestrator.initialize()
    auth_res = await orchestrator.db.authenticate_user(req.email, req.password)
    if not auth_res:
        raise HTTPException(status_code=401, detail="البريد الإلكتروني أو كلمة المرور غير صحيحة.")
    user, org = auth_res
    token = create_access_token(
        user_id=int(user.id or 1),
        org_id=int(org.id or 1),
        email=user.email,
        role=user.role,
    )
    return {
        "status": "success",
        "access_token": token,
        "user": user.model_dump(),
        "organization": org.model_dump(),
    }


@app.get("/api/auth/me")
async def api_me(request: Request) -> Dict[str, Any]:
    await orchestrator.initialize()
    payload = get_current_user_payload(request)
    org_id = int(payload["org_id"]) if payload and payload.get("org_id") else 1
    user_id = int(payload["sub"]) if payload and payload.get("sub") else 1
    user = await orchestrator.db.get_user_by_id(user_id)
    org = await orchestrator.db.get_organization(org_id)
    return {
        "user": user.model_dump() if user else None,
        "organization": org.model_dump() if org else None,
        "plans": PLAN_DEFINITIONS,
    }


# ==========================================
# SaaS Billing, Quotas & Super Admin APIs
# ==========================================
@app.get("/api/plans")
async def api_list_plans() -> Dict[str, Any]:
    return {"plans": PLAN_DEFINITIONS}


@app.post("/api/billing/upgrade")
async def api_upgrade_plan(req: UpgradePlanRequest, request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    try:
        updated_org = await orchestrator.db.upgrade_organization_plan(
            org_id=org_id,
            plan_tier=req.plan_tier,
            billing_cycle=req.billing_cycle,
        )
        await orchestrator.db.log_activity(
            agent_name="BillingEngine",
            action="ترقية باقة الاشتراك",
            details=f"تمت ترقية الباقة إلى {req.plan_tier.upper()}",
            org_id=org_id,
            level="success",
        )
        return {"status": "success", "organization": updated_org.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/superadmin/upgrade-org")
async def api_superadmin_upgrade(req: SuperAdminUpgradeRequest) -> Dict[str, Any]:
    updated_org = await orchestrator.db.upgrade_organization_plan(
        org_id=req.org_id,
        plan_tier=req.plan_tier,
    )
    return {"status": "success", "organization": updated_org.model_dump()}


# ==========================================
# Company Profiler & Services Catalog APIs
# ==========================================
@app.post("/api/company/profile-analyze")
async def api_company_profile_analyze(
    req: CompanyProfileAnalyzeRequest, request: Request
) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    res = await orchestrator.company_profiler.run(
        website_url=req.website_url,
        raw_profile_text=req.raw_profile_text,
        company_name_hint=req.company_name_hint,
        industry_hint=req.industry_hint,
        org_id=org_id,
    )
    return {"status": "success", **res}


@app.post("/api/company/profile-save")
async def api_company_profile_save(
    req: CompanyProfileSaveRequest, request: Request
) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    cp = req.company_profile
    saved = await orchestrator.db.save_tenant_settings(
        org_id=org_id,
        company_profile=cp,
        icp={
            "target_industries": cp.get("target_industries", []),
            "value_proposition_ar": cp.get("value_proposition_ar", ""),
            "value_proposition_en": cp.get("value_proposition_en", ""),
            "sender_persona_ar": cp.get("sender_persona_ar", ""),
        },
    )
    return {"status": "success", "tenant_settings": saved}


# ==========================================
# Overview & Pipeline Control (Tenant Scoped)
# ==========================================
@app.get("/api/overview")
async def get_overview(request: Request) -> Dict[str, Any]:
    await orchestrator.initialize()
    org_id = get_current_org_id(request)

    leads = await orchestrator.db.list_leads(org_id=org_id)
    drafts = await orchestrator.db.list_email_drafts(org_id=org_id)
    replies = await orchestrator.db.list_replies(org_id=org_id)
    proposals = await orchestrator.db.list_proposals(org_id=org_id)
    analytics = await orchestrator.analyst.run(org_id=org_id)
    sent_today = await orchestrator.db.count_sent_today(org_id=org_id)
    org = await orchestrator.db.get_organization(org_id)
    all_orgs = await orchestrator.db.list_organizations()
    health = await orchestrator.get_system_health(org_id=org_id)
    activity_logs = await orchestrator.db.list_activity_logs(org_id=org_id, limit=25)

    return {
        "system": {
            "name": orchestrator.settings.system.name,
            "domain": orchestrator.settings.system.domain,
            "dry_run": orchestrator.settings.system.dry_run,
            "provider": orchestrator.settings.llm.provider,
            "model": orchestrator.settings.llm.model,
            "daily_cap": orchestrator.settings.sender.daily_send_cap,
            "sent_today": sent_today,
            "calendar_link": orchestrator.settings.sender.calendar_booking_link,
        },
        "organization": org.model_dump() if org else None,
        "all_organizations": [o.model_dump() for o in all_orgs],
        "plans": PLAN_DEFINITIONS,
        "health": health,
        "analytics": analytics,
        "leads": [l.model_dump() for l in leads],
        "drafts": [d.model_dump() for d in drafts],
        "replies": [r.model_dump() for r in replies],
        "proposals": [p.model_dump() for p in proposals],
        "activity_logs": activity_logs,
    }


@app.post("/api/pipeline/run")
async def run_pipeline(req: RunPipelineRequest, request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    try:
        return await orchestrator.run_full_pipeline(
            language=req.language,
            limit=req.limit,
            auto_approve=req.auto_approve,
            industry=req.industry,
            region=req.region,
            org_id=org_id,
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))


@app.post("/api/agents/scout")
async def run_scout_only(req: ScoutRequest, request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    try:
        discovered = await orchestrator.scout.run(
            industry=req.industry,
            region=req.region,
            language=req.language,
            limit=req.limit,
            org_id=org_id,
        )
        ids = [int(l.id) for l in discovered if l.id is not None]
        enriched = await orchestrator.enricher.run(lead_ids=ids)
        return {
            "discovered_count": len(discovered),
            "enriched_count": len(enriched),
        }
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))


# ==========================================
# Leads Management & CSV Import
# ==========================================
@app.post("/api/leads")
async def create_manual_lead(req: CreateLeadRequest, request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    try:
        await orchestrator.db.check_and_consume_quota(org_id=org_id, resource="leads", amount=1)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))

    lead = Lead(
        org_id=org_id,
        company_name=req.company_name,
        website=req.website,
        industry=req.industry,
        region=req.region,
        contact_name=req.contact_name,
        contact_role=req.contact_role,
        contact_email=req.contact_email,
        company_summary=req.company_summary,
        language=req.language,
        status=LeadStatus.DISCOVERED,
    )
    lead_id = await orchestrator.db.upsert_lead(lead)
    await orchestrator.enricher.run(lead_ids=[lead_id])
    updated = await orchestrator.db.get_lead(lead_id)
    return {"lead": updated.model_dump() if updated else None}


@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int) -> Dict[str, Any]:
    with orchestrator.db._connect() as conn:
        conn.execute("DELETE FROM email_drafts WHERE lead_id = ?", (lead_id,))
        conn.execute("DELETE FROM inbox_replies WHERE lead_id = ?", (lead_id,))
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()
    return {"deleted": lead_id}


@app.post("/api/leads/{lead_id}/enrich")
async def enrich_single_lead(lead_id: int) -> Dict[str, Any]:
    res = await orchestrator.enricher.run(lead_ids=[lead_id])
    if not res:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": res[0].model_dump()}


@app.post("/api/leads/{lead_id}/write")
async def write_single_lead_sequence(lead_id: int) -> Dict[str, Any]:
    lead = await orchestrator.db.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    drafts = await orchestrator.writer.write_sequence_for_lead(lead)
    return {"drafts_created": len(drafts), "drafts": [d.model_dump() for d in drafts]}


@app.post("/api/leads/import-csv")
async def import_leads_csv(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    imported_ids: List[int] = []

    for row in reader:
        company = (row.get("company_name") or row.get("الشركة") or "").strip()
        email = (row.get("contact_email") or row.get("البريد") or "").strip()
        if not company and not email:
            continue
        lead = Lead(
            org_id=org_id,
            company_name=company or "شركة مستوردة",
            website=(row.get("website") or row.get("الموقع") or "").strip(),
            industry=(row.get("industry") or row.get("القطاع") or "SaaS & Tech").strip(),
            region=(row.get("region") or row.get("المنطقة") or "المملكة العربية السعودية").strip(),
            contact_name=(row.get("contact_name") or row.get("الاسم") or "").strip(),
            contact_role=(row.get("contact_role") or row.get("المنصب") or "").strip(),
            contact_email=email,
            company_summary=(row.get("company_summary") or row.get("نبذة") or "").strip(),
            language=(row.get("language") or row.get("اللغة") or "ar").strip(),
            status=LeadStatus.DISCOVERED,
        )
        lid = await orchestrator.db.upsert_lead(lead)
        imported_ids.append(lid)

    if imported_ids:
        await orchestrator.enricher.run(lead_ids=imported_ids)

    return {"imported_count": len(imported_ids), "lead_ids": imported_ids}


# ==========================================
# Approval Ladder & Draft Editing
# ==========================================
@app.post("/api/agents/write")
async def run_writer_all(request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    drafts = await orchestrator.writer.run(org_id=org_id)
    return {"drafts_created": len(drafts)}


@app.post("/api/drafts/approve-all")
async def approve_all_drafts(request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    count = await orchestrator.approve_all_pending(org_id=org_id)
    return {"approved_count": count}


@app.post("/api/drafts/{draft_id}")
async def update_single_draft(draft_id: int, req: DraftActionRequest) -> Dict[str, Any]:
    status_map = {
        "approve": ApprovalStatus.APPROVED,
        "reject": ApprovalStatus.REJECTED,
        "pending": ApprovalStatus.PENDING,
    }
    new_status = status_map.get(req.action.lower(), ApprovalStatus.PENDING)
    await orchestrator.db.update_draft_approval(
        draft_id=draft_id,
        status=new_status,
        subject=req.subject,
        body=req.body,
    )
    return {"draft_id": draft_id, "status": new_status.value}


# ==========================================
# Outbox Sender, Autopilot & Reply Handler
# ==========================================
@app.post("/api/agents/send")
async def trigger_sender(request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    try:
        return await orchestrator.sender.run(org_id=org_id)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))


@app.post("/api/autopilot/toggle")
async def api_autopilot_toggle(req: AutopilotToggleRequest, request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    orchestrator.settings.system.autopilot_enabled = req.enabled
    save_settings(orchestrator.settings)
    await orchestrator.db.log_activity(
        agent_name="Autopilot",
        action="تغيير حالة الطيار الآلي",
        details="تم تفعيل الطيار الآلي" if req.enabled else "تم إيقاف الطيار الآلي",
        org_id=org_id,
    )
    return {"status": "success", "autopilot_enabled": req.enabled}


@app.post("/api/autopilot/run-cycle")
async def api_autopilot_run_cycle(request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    return await scheduler.run_single_cycle(org_id=org_id)


@app.post("/api/agents/simulate-reply")
async def simulate_reply(req: SimulateReplyRequest) -> Dict[str, Any]:
    if not req.from_email or not req.body:
        raise HTTPException(status_code=400, detail="from_email and body are required")

    processed = await orchestrator.handler.run(
        simulated_replies=[
            {
                "from_email": req.from_email.strip(),
                "subject": req.subject,
                "body": req.body,
            }
        ]
    )
    return {"processed": [p.model_dump() for p in processed]}


# ==========================================
# Proposals Engine Bridge & Public Showcase APIs
# ==========================================
@app.post("/api/proposals/generate")
async def generate_proposal_endpoint(
    req: GenerateProposalRequest, request: Request
) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    if not req.transcript_text.strip():
        raise HTTPException(
            status_code=400, detail="يرجى إدخال نص تفريغ المكالمة أو ملخص الاجتماع."
        )
    try:
        return await orchestrator.generate_proposal_for_lead(
            lead_id=req.lead_id,
            transcript_text=req.transcript_text,
            custom_notes=req.custom_notes,
            org_id=org_id,
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/proposals/public/{slug}")
async def api_get_public_proposal(slug: str) -> Dict[str, Any]:
    proposal = await orchestrator.db.get_proposal_by_slug(slug, increment_view=True)
    if not proposal:
        raise HTTPException(status_code=404, detail="العرض المطلوب غير موجود.")
    return proposal.model_dump()


@app.post("/api/proposals/public/{slug}/accept")
async def api_accept_public_proposal(
    slug: str, req: AcceptProposalRequest
) -> Dict[str, Any]:
    proposal = await orchestrator.db.accept_proposal_by_slug(slug, req.accepted_by)
    if not proposal:
        raise HTTPException(status_code=404, detail="العرض المطلوب غير موجود.")
    await orchestrator.db.log_activity(
        agent_name="ProposalViewer",
        action="اعتماد إلكتروني للعرض من العميل",
        details=f"قام ({req.accepted_by}) باعتماد العرض ({proposal.slug}) لشركة {proposal.client_company}",
        org_id=proposal.org_id,
        level="success",
    )
    return proposal.model_dump()


# ==========================================
# Connection Diagnostics & Live Settings APIs
# ==========================================
@app.post("/api/diagnostics/ai")
async def api_diagnostics_ai() -> Dict[str, Any]:
    return await test_ai_engine_connection(orchestrator.settings)


@app.post("/api/diagnostics/email")
async def api_diagnostics_email(req: EmailDiagnosticsRequest) -> Dict[str, Any]:
    return await test_email_connections(
        smtp_host=req.smtp_host,
        smtp_port=req.smtp_port,
        smtp_username=req.smtp_username,
        smtp_password=req.smtp_password,
        imap_host=req.imap_host,
        imap_port=req.imap_port,
        imap_username=req.imap_username,
        imap_password=req.imap_password,
    )


@app.get("/api/settings")
async def get_settings(request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    tenant_cfg = await orchestrator.db.get_tenant_settings(org_id=org_id)
    return {
        "system": orchestrator.settings.system.model_dump(),
        "llm": {
            "provider": orchestrator.settings.llm.provider,
            "model": orchestrator.settings.llm.model,
            "has_gemini_key": bool(
                orchestrator.settings.llm.gemini_api_key
                and orchestrator.settings.llm.gemini_api_key != "your_gemini_api_key_here"
            ),
        },
        "sender": {
            "dry_run": orchestrator.settings.system.dry_run,
            "daily_send_cap": orchestrator.settings.sender.daily_send_cap,
            "sender_name": orchestrator.settings.sender.sender_name,
            "sender_email": orchestrator.settings.sender.sender_email,
            "calendar_booking_link": orchestrator.settings.sender.calendar_booking_link,
            "smtp_host": orchestrator.settings.sender.smtp_host,
            "smtp_port": orchestrator.settings.sender.smtp_port,
            "smtp_username": orchestrator.settings.sender.smtp_username,
            "imap_host": orchestrator.settings.sender.imap_host,
            "imap_port": orchestrator.settings.sender.imap_port,
            "sending_window_start_hour": orchestrator.settings.sender.sending_window_start_hour,
            "sending_window_end_hour": orchestrator.settings.sender.sending_window_end_hour,
        },
        "writer": orchestrator.settings.writer.model_dump(),
        "icp": orchestrator.settings.icp.model_dump(),
        "company_profile": tenant_cfg.get("company_profile", {}),
    }


@app.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest, request: Request) -> Dict[str, Any]:
    org_id = get_current_org_id(request)
    if req.dry_run is not None:
        orchestrator.settings.system.dry_run = req.dry_run
    if req.auto_approve_sequences is not None:
        orchestrator.settings.system.auto_approve_sequences = req.auto_approve_sequences
    if req.ai_provider is not None:
        orchestrator.settings.llm.provider = req.ai_provider
    if req.ai_model is not None:
        orchestrator.settings.llm.model = req.ai_model
    if req.gemini_api_key:
        orchestrator.settings.llm.gemini_api_key = req.gemini_api_key
    if req.openai_api_key:
        orchestrator.settings.llm.openai_api_key = req.openai_api_key
    if req.calendar_booking_link is not None:
        orchestrator.settings.sender.calendar_booking_link = req.calendar_booking_link
    if req.sender_name is not None:
        orchestrator.settings.sender.sender_name = req.sender_name
    if req.sender_email is not None:
        orchestrator.settings.sender.sender_email = req.sender_email
    if req.daily_send_cap is not None:
        orchestrator.settings.sender.daily_send_cap = req.daily_send_cap
    if req.smtp_host is not None:
        orchestrator.settings.sender.smtp_host = req.smtp_host
    if req.smtp_port is not None:
        orchestrator.settings.sender.smtp_port = req.smtp_port
    if req.smtp_username is not None:
        orchestrator.settings.sender.smtp_username = req.smtp_username
    if req.smtp_password:
        orchestrator.settings.sender.smtp_password = req.smtp_password
    if req.imap_host is not None:
        orchestrator.settings.sender.imap_host = req.imap_host
    if req.imap_port is not None:
        orchestrator.settings.sender.imap_port = req.imap_port
    if req.sending_window_start_hour is not None:
        orchestrator.settings.sender.sending_window_start_hour = req.sending_window_start_hour
    if req.sending_window_end_hour is not None:
        orchestrator.settings.sender.sending_window_end_hour = req.sending_window_end_hour
    if req.min_qualification_score is not None:
        orchestrator.settings.icp.min_qualification_score = req.min_qualification_score
    if req.max_words_step_1 is not None:
        orchestrator.settings.writer.max_words_step_1 = req.max_words_step_1
    if req.banned_buzzwords_ar is not None:
        orchestrator.settings.writer.banned_buzzwords_ar = req.banned_buzzwords_ar
    if req.banned_buzzwords_en is not None:
        orchestrator.settings.writer.banned_buzzwords_en = req.banned_buzzwords_en
    if req.value_proposition_ar is not None:
        orchestrator.settings.icp.value_proposition_ar = req.value_proposition_ar
    if req.value_proposition_en is not None:
        orchestrator.settings.icp.value_proposition_en = req.value_proposition_en

    # Persist permanently to settings.yaml and tenant_settings DB
    save_settings(orchestrator.settings)
    await orchestrator.db.save_tenant_settings(
        org_id=org_id,
        icp=orchestrator.settings.icp.model_dump(),
        sender={
            "sender_name": orchestrator.settings.sender.sender_name,
            "sender_email": orchestrator.settings.sender.sender_email,
            "calendar_booking_link": orchestrator.settings.sender.calendar_booking_link,
            "daily_send_cap": orchestrator.settings.sender.daily_send_cap,
            "smtp_host": orchestrator.settings.sender.smtp_host,
            "smtp_port": orchestrator.settings.sender.smtp_port,
        },
        writer=orchestrator.settings.writer.model_dump(),
    )

    orchestrator.refresh_llm_clients()
    return {"status": "success", "message": "تم حفظ وتحديث كافة الإعدادات بشكل دائم"}


# ==========================================
# Exports (CSV & JSON)
# ==========================================
@app.get("/api/export/csv")
async def download_csv_export() -> FileResponse:
    path = await orchestrator.exporter.export_to_csv("data/autodeal_export.csv")
    return FileResponse(
        path=str(path),
        media_type="text/csv",
        filename="autodeal_leads_and_sequences.csv",
    )


@app.get("/api/export/json")
async def download_json_export() -> FileResponse:
    path = await orchestrator.exporter.export_to_json("data/autodeal_export.json")
    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename="autodeal_leads_and_sequences.json",
    )
