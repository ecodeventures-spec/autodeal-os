"""Asynchronous Multi-Tenant SQLite Database Layer for NUDHUJ AutoDeal OS SaaS."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterator, List, Optional, Tuple

from src.core.auth import hash_password, slugify_org, verify_password
from src.core.models import (
    ApprovalStatus,
    Campaign,
    CompanyProfile,
    EmailDraft,
    InboxReply,
    InteractiveProposal,
    Lead,
    LeadStatus,
    Organization,
    PLAN_DEFINITIONS,
    PlanTier,
    ReplyIntent,
    User,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    domain TEXT DEFAULT '',
    industry TEXT DEFAULT 'حلول الأعمال والخدمات (B2B)',
    plan_tier TEXT DEFAULT 'free',
    billing_cycle TEXT DEFAULT 'monthly',
    subscription_status TEXT DEFAULT 'active',
    leads_quota INTEGER DEFAULT 25,
    leads_used INTEGER DEFAULT 0,
    emails_quota INTEGER DEFAULT 50,
    emails_used INTEGER DEFAULT 0,
    proposals_quota INTEGER DEFAULT 3,
    proposals_used INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'owner',
    onboarding_completed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS tenant_settings (
    org_id INTEGER PRIMARY KEY,
    company_profile_json TEXT DEFAULT '{}',
    icp_json TEXT DEFAULT '{}',
    sender_json TEXT DEFAULT '{}',
    writer_json TEXT DEFAULT '{}',
    llm_json TEXT DEFAULT '{}',
    system_json TEXT DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizations (id)
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    region TEXT DEFAULT 'المملكة العربية السعودية',
    language TEXT DEFAULT 'ar',
    value_proposition TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    campaign_id INTEGER DEFAULT 1,
    company_name TEXT NOT NULL,
    website TEXT DEFAULT '',
    industry TEXT DEFAULT '',
    region TEXT DEFAULT '',
    contact_name TEXT DEFAULT '',
    contact_role TEXT DEFAULT '',
    contact_email TEXT DEFAULT '',
    email_verified INTEGER DEFAULT 0,
    company_summary TEXT DEFAULT '',
    pain_points TEXT DEFAULT '',
    personalization_hook TEXT DEFAULT '',
    qualification_score INTEGER DEFAULT 0,
    score_reasoning TEXT DEFAULT '',
    language TEXT DEFAULT 'ar',
    status TEXT DEFAULT 'discovered',
    proposal_status TEXT DEFAULT 'none',
    proposal_url TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
);

CREATE TABLE IF NOT EXISTS email_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER DEFAULT 1,
    step_number INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    word_count INTEGER DEFAULT 0,
    language TEXT DEFAULT 'ar',
    approval_status TEXT DEFAULT 'pending',
    scheduled_at TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads (id)
);

CREATE TABLE IF NOT EXISTS inbox_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    lead_id INTEGER NOT NULL,
    from_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    intent TEXT DEFAULT 'question',
    confidence REAL DEFAULT 0.9,
    ai_suggested_reply TEXT DEFAULT '',
    reply_approved INTEGER DEFAULT 0,
    received_at TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads (id)
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    lead_id INTEGER,
    slug TEXT NOT NULL UNIQUE,
    title_ar TEXT NOT NULL,
    title_en TEXT DEFAULT '',
    client_company TEXT NOT NULL,
    client_contact TEXT DEFAULT '',
    client_role TEXT DEFAULT '',
    industry TEXT DEFAULT '',
    language TEXT DEFAULT 'ar',
    template_id TEXT DEFAULT 'universal-b2b',
    proposal_json TEXT NOT NULL,
    total_amount REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'SAR',
    white_label INTEGER DEFAULT 0,
    status TEXT DEFAULT 'generated',
    views_count INTEGER DEFAULT 0,
    accepted_at TEXT,
    accepted_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL DEFAULT 1,
    agent_name TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT DEFAULT '',
    level TEXT DEFAULT 'info',
    created_at TEXT NOT NULL
);
"""


class QuotaExceededError(Exception):
    """Raised when a tenant organization exceeds its current SaaS plan quota."""


class DatabaseManager:
    """Manages SQLite persistence asynchronously for Multi-Tenant SaaS Organizations, Users, Leads, Drafts, Replies, and Proposals."""

    def __init__(self, db_path: str = "data/autodeal_os.db") -> None:
        p = Path(db_path)
        if not p.is_absolute():
            from src.core.config import BASE_DIR
            p = BASE_DIR / p
        self.db_path = p.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    async def initialize(self) -> None:
        self._init_sync()

    def _init_sync(self) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            for table in ("campaigns", "leads", "email_drafts", "inbox_replies"):
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN org_id INTEGER NOT NULL DEFAULT 1")
                except Exception:
                    pass
            try:
                conn.execute("ALTER TABLE leads ADD COLUMN proposal_status TEXT DEFAULT 'none'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE leads ADD COLUMN proposal_url TEXT DEFAULT ''")
            except Exception:
                pass

            # Seed Organization #1 (NUDHUJ HQ - Enterprise Business Scale)
            org_row = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()
            if org_row and org_row[0] == 0:
                biz_plan = PLAN_DEFINITIONS[PlanTier.BUSINESS.value]
                conn.execute(
                    """
                    INSERT INTO organizations (
                        id, name, slug, domain, industry, plan_tier, billing_cycle,
                        subscription_status, leads_quota, leads_used, emails_quota,
                        emails_used, proposals_quota, proposals_used, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "نضج لحلول الأعمال الذكية (NUDHUJ)",
                        "nudhuj-hq",
                        "https://autodeal.nudhuj.com",
                        "حلول الأعمال والذكاء الاصطناعي والعروض التفاعلية",
                        PlanTier.BUSINESS.value,
                        "yearly",
                        "active",
                        biz_plan["leads_quota"],
                        0,
                        biz_plan["emails_quota"],
                        0,
                        biz_plan["proposals_quota"],
                        0,
                        now,
                    ),
                )

            # Seed SuperAdmin User if none exists
            user_row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            if user_row and user_row[0] == 0:
                conn.execute(
                    """
                    INSERT INTO users (
                        id, org_id, full_name, email, password_hash, role, onboarding_completed, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        1,
                        "المدير التنفيذي | نضج (Super Admin)",
                        "admin@nudhuj.com",
                        hash_password("Nudhuj@2026"),
                        "superadmin",
                        1,
                        now,
                    ),
                )

            # Seed default tenant settings for Org #1
            ts_row = conn.execute("SELECT COUNT(*) FROM tenant_settings WHERE org_id = 1").fetchone()
            if ts_row and ts_row[0] == 0:
                default_profile = CompanyProfile().model_dump()
                conn.execute(
                    """
                    INSERT INTO tenant_settings (org_id, company_profile_json, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (1, json.dumps(default_profile, ensure_ascii=False), now),
                )

            # Seed default campaign
            row = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()
            if row and row[0] == 0:
                conn.execute(
                    """
                    INSERT INTO campaigns (org_id, name, industry, region, language, value_proposition, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "حملة النمو وتطوير الأعمال الذكية (NUDHUJ AutoDeal)",
                        "SaaS & Enterprise B2B",
                        "المملكة العربية السعودية والخليج",
                        "ar",
                        "حلول متكاملة لأتمتة المبيعات والعروض الفنية والمالية وزيادة العائد بنسبة 40%",
                        "active",
                        now,
                    ),
                )
            conn.commit()

    # ==========================================
    # SaaS Auth, Organizations & Quotas
    # ==========================================
    async def register_tenant_and_user(
        self,
        company_name: str,
        full_name: str,
        email: str,
        password: str,
        industry: str = "التقنية والخدمات للأعمال (B2B)",
        website: str = "",
        plan_tier: str = "free",
    ) -> Tuple[Organization, User]:
        return self._register_tenant_and_user_sync(
            company_name,
            full_name,
            email,
            password,
            industry,
            website,
            plan_tier,
        )

    def _register_tenant_and_user_sync(
        self,
        company_name: str,
        full_name: str,
        email: str,
        password: str,
        industry: str,
        website: str,
        plan_tier: str,
    ) -> Tuple[Organization, User]:
        email_clean = email.strip().lower()
        now = utc_now_iso()
        plan_key = plan_tier if plan_tier in PLAN_DEFINITIONS else PlanTier.FREE.value
        plan_spec = PLAN_DEFINITIONS[plan_key]
        slug = slugify_org(company_name)

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE LOWER(email) = ?", (email_clean,)
            ).fetchone()
            if existing:
                raise ValueError("البريد الإلكتروني مسجل مسبقاً. يرجى تسجيل الدخول.")

            cur_org = conn.execute(
                """
                INSERT INTO organizations (
                    name, slug, domain, industry, plan_tier, billing_cycle,
                    subscription_status, leads_quota, leads_used, emails_quota,
                    emails_used, proposals_quota, proposals_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_name.strip(),
                    slug,
                    website.strip(),
                    industry.strip(),
                    plan_key,
                    "monthly",
                    "active",
                    plan_spec["leads_quota"],
                    0,
                    plan_spec["emails_quota"],
                    0,
                    plan_spec["proposals_quota"],
                    0,
                    now,
                ),
            )
            org_id = int(cur_org.lastrowid or 1)

            cur_user = conn.execute(
                """
                INSERT INTO users (
                    org_id, full_name, email, password_hash, role, onboarding_completed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    full_name.strip(),
                    email_clean,
                    hash_password(password),
                    "owner",
                    0,
                    now,
                ),
            )
            user_id = int(cur_user.lastrowid or 1)

            # Initialize custom company profile for this new tenant
            profile = CompanyProfile(
                company_name_ar=company_name.strip(),
                company_name_en=company_name.strip(),
                website=website.strip() or "https://example.com",
                industry=industry.strip(),
            )
            conn.execute(
                """
                INSERT INTO tenant_settings (org_id, company_profile_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (org_id, json.dumps(profile.model_dump(), ensure_ascii=False), now),
            )

            # Create initial default campaign for this tenant
            conn.execute(
                """
                INSERT INTO campaigns (org_id, name, industry, region, language, value_proposition, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    f"الحملة الأولى - {company_name.strip()}",
                    industry.strip(),
                    "المملكة العربية السعودية",
                    "ar",
                    profile.value_proposition_ar,
                    "active",
                    now,
                ),
            )
            conn.commit()

        org = self._get_organization_sync(org_id)
        user = self._get_user_by_id_sync(user_id)
        assert org is not None and user is not None
        return org, user

    async def authenticate_user(self, email: str, password: str) -> Optional[Tuple[User, Organization]]:
        return self._authenticate_user_sync( email, password)

    def _authenticate_user_sync(self, email: str, password: str) -> Optional[Tuple[User, Organization]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE LOWER(email) = ?", (email.strip().lower(),)
            ).fetchone()
            if not row:
                return None
            if not verify_password(password, row["password_hash"]):
                return None
            user = self._row_to_user(dict(row))
            org = self._get_organization_sync(user.org_id)
            if not org:
                return None
            return user, org

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self._get_user_by_id_sync( user_id)

    def _get_user_by_id_sync(self, user_id: int) -> Optional[User]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._row_to_user(dict(row)) if row else None

    @staticmethod
    def _row_to_user(d: Dict[str, Any]) -> User:
        d.pop("password_hash", None)
        d["onboarding_completed"] = bool(d.get("onboarding_completed", 0))
        return User(**d)

    async def mark_onboarding_completed(self, user_id: int) -> None:
        self._mark_onboarding_completed_sync( user_id)

    def _mark_onboarding_completed_sync(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET onboarding_completed = 1 WHERE id = ?", (user_id,))
            conn.commit()

    async def get_organization(self, org_id: int) -> Optional[Organization]:
        return self._get_organization_sync( org_id)

    def _get_organization_sync(self, org_id: int) -> Optional[Organization]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
            return Organization(**dict(row)) if row else None

    async def list_organizations(self) -> List[Organization]:
        return self._list_organizations_sync()

    def _list_organizations_sync(self) -> List[Organization]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM organizations ORDER BY id DESC").fetchall()
            return [Organization(**dict(r)) for r in rows]

    async def upgrade_organization_plan(
        self, org_id: int, plan_tier: str, billing_cycle: str = "monthly"
    ) -> Organization:
        return self._upgrade_organization_plan_sync( org_id, plan_tier, billing_cycle
        )

    def _upgrade_organization_plan_sync(
        self, org_id: int, plan_tier: str, billing_cycle: str = "monthly"
    ) -> Organization:
        if plan_tier not in PLAN_DEFINITIONS:
            raise ValueError(f"Unknown plan tier: {plan_tier}")
        spec = PLAN_DEFINITIONS[plan_tier]
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE organizations SET
                    plan_tier = ?, billing_cycle = ?, subscription_status = 'active',
                    leads_quota = ?, emails_quota = ?, proposals_quota = ?
                WHERE id = ?
                """,
                (
                    plan_tier,
                    billing_cycle,
                    spec["leads_quota"],
                    spec["emails_quota"],
                    spec["proposals_quota"],
                    org_id,
                ),
            )
            conn.commit()
        org = self._get_organization_sync(org_id)
        if not org:
            raise ValueError(f"Organization {org_id} not found")
        return org

    async def check_and_consume_quota(
        self, org_id: int, resource: str, amount: int = 1
    ) -> Organization:
        return self._check_and_consume_quota_sync( org_id, resource, amount
        )

    def _check_and_consume_quota_sync(
        self, org_id: int, resource: str, amount: int = 1
    ) -> Organization:
        org = self._get_organization_sync(org_id)
        if not org:
            raise ValueError(f"Organization {org_id} not found")

        col_used = f"{resource}_used"
        col_quota = f"{resource}_quota"
        used_val = getattr(org, col_used, 0)
        quota_val = getattr(org, col_quota, 0)

        if used_val + amount > quota_val:
            resource_labels = {
                "leads": "استكشاف العملاء المحتملين",
                "emails": "إرسال رسائل البريد",
                "proposals": "توليد العروض الفنية والمالية",
            }
            label = resource_labels.get(resource, resource)
            raise QuotaExceededError(
                f"لقد وصلت إلى الحد الأقصى المسموح به في باقتك الحالية ({org.plan_tier.upper()}) لـ {label} "
                f"({used_val}/{quota_val}). يرجى ترقية الباقة للاستمرار."
            )

        with self._connect() as conn:
            conn.execute(
                f"UPDATE organizations SET {col_used} = {col_used} + ? WHERE id = ?",
                (amount, org_id),
            )
            conn.commit()

        updated = self._get_organization_sync(org_id)
        assert updated is not None
        return updated

    # ==========================================
    # Tenant Settings & Company Profile Persistence
    # ==========================================
    async def get_tenant_settings(self, org_id: int = 1) -> Dict[str, Any]:
        return self._get_tenant_settings_sync( org_id)

    def _get_tenant_settings_sync(self, org_id: int = 1) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_settings WHERE org_id = ?", (org_id,)
            ).fetchone()
            if not row:
                default_cp = CompanyProfile().model_dump()
                return {
                    "org_id": org_id,
                    "company_profile": default_cp,
                    "icp": {},
                    "sender": {},
                    "writer": {},
                    "llm": {},
                    "system": {},
                }
            return {
                "org_id": org_id,
                "company_profile": json.loads(row["company_profile_json"] or "{}"),
                "icp": json.loads(row["icp_json"] or "{}"),
                "sender": json.loads(row["sender_json"] or "{}"),
                "writer": json.loads(row["writer_json"] or "{}"),
                "llm": json.loads(row["llm_json"] or "{}"),
                "system": json.loads(row["system_json"] or "{}"),
                "updated_at": row["updated_at"],
            }

    async def save_tenant_settings(
        self,
        org_id: int = 1,
        company_profile: Optional[Dict[str, Any]] = None,
        icp: Optional[Dict[str, Any]] = None,
        sender: Optional[Dict[str, Any]] = None,
        writer: Optional[Dict[str, Any]] = None,
        llm: Optional[Dict[str, Any]] = None,
        system: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._save_tenant_settings_sync(
            org_id,
            company_profile,
            icp,
            sender,
            writer,
            llm,
            system,
        )

    def _save_tenant_settings_sync(
        self,
        org_id: int = 1,
        company_profile: Optional[Dict[str, Any]] = None,
        icp: Optional[Dict[str, Any]] = None,
        sender: Optional[Dict[str, Any]] = None,
        writer: Optional[Dict[str, Any]] = None,
        llm: Optional[Dict[str, Any]] = None,
        system: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current = self._get_tenant_settings_sync(org_id)
        now = utc_now_iso()

        if company_profile is not None:
            merged_cp = {**current.get("company_profile", {}), **company_profile}
        else:
            merged_cp = current.get("company_profile", {})

        merged_icp = {**current.get("icp", {}), **(icp or {})}
        merged_sender = {**current.get("sender", {}), **(sender or {})}
        merged_writer = {**current.get("writer", {}), **(writer or {})}
        merged_llm = {**current.get("llm", {}), **(llm or {})}
        merged_system = {**current.get("system", {}), **(system or {})}

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_settings (
                    org_id, company_profile_json, icp_json, sender_json,
                    writer_json, llm_json, system_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id) DO UPDATE SET
                    company_profile_json = excluded.company_profile_json,
                    icp_json = excluded.icp_json,
                    sender_json = excluded.sender_json,
                    writer_json = excluded.writer_json,
                    llm_json = excluded.llm_json,
                    system_json = excluded.system_json,
                    updated_at = excluded.updated_at
                """,
                (
                    org_id,
                    json.dumps(merged_cp, ensure_ascii=False),
                    json.dumps(merged_icp, ensure_ascii=False),
                    json.dumps(merged_sender, ensure_ascii=False),
                    json.dumps(merged_writer, ensure_ascii=False),
                    json.dumps(merged_llm, ensure_ascii=False),
                    json.dumps(merged_system, ensure_ascii=False),
                    now,
                ),
            )
            if company_profile and company_profile.get("company_name_ar"):
                conn.execute(
                    "UPDATE organizations SET name = ?, industry = COALESCE(?, industry), domain = COALESCE(?, domain) WHERE id = ?",
                    (
                        company_profile.get("company_name_ar"),
                        company_profile.get("industry"),
                        company_profile.get("website"),
                        org_id,
                    ),
                )
            conn.commit()
        return self._get_tenant_settings_sync(org_id)

    # ==========================================
    # Activity Logs
    # ==========================================
    async def log_activity(
        self, agent_name: str, action: str, details: str = "", org_id: int = 1, level: str = "info"
    ) -> None:
        self._log_activity_sync( agent_name, action, details, org_id, level
        )

    def _log_activity_sync(
        self, agent_name: str, action: str, details: str = "", org_id: int = 1, level: str = "info"
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity_logs (org_id, agent_name, action, details, level, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (org_id, agent_name, action, details, level, utc_now_iso()),
            )
            conn.commit()

    async def list_activity_logs(self, org_id: int = 1, limit: int = 30) -> List[Dict[str, Any]]:
        return self._list_activity_logs_sync( org_id, limit)

    def _list_activity_logs_sync(self, org_id: int = 1, limit: int = 30) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM activity_logs WHERE org_id = ? ORDER BY id DESC LIMIT ?",
                (org_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ==========================================
    # Campaigns CRUD
    # ==========================================
    async def create_campaign(self, campaign: Campaign) -> int:
        return self._create_campaign_sync( campaign)

    def _create_campaign_sync(self, campaign: Campaign) -> int:
        now = utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO campaigns (org_id, name, industry, region, language, value_proposition, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.org_id or 1,
                    campaign.name,
                    campaign.industry,
                    campaign.region,
                    campaign.language,
                    campaign.value_proposition,
                    campaign.status,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid or 1)

    async def list_campaigns(self, org_id: Optional[int] = None) -> List[Campaign]:
        return self._list_campaigns_sync( org_id)

    def _list_campaigns_sync(self, org_id: Optional[int] = None) -> List[Campaign]:
        with self._connect() as conn:
            if org_id is not None:
                rows = conn.execute(
                    "SELECT * FROM campaigns WHERE org_id = ? ORDER BY id DESC", (org_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
            return [Campaign(**dict(r)) for r in rows]

    # ==========================================
    # Leads CRUD (Multi-Tenant Scoped)
    # ==========================================
    async def upsert_lead(self, lead: Lead) -> int:
        return self._upsert_lead_sync( lead)

    def _upsert_lead_sync(self, lead: Lead) -> int:
        now = utc_now_iso()
        org_id = lead.org_id or 1
        status_str = lead.status.value if isinstance(lead.status, LeadStatus) else str(lead.status)
        with self._connect() as conn:
            if lead.id:
                existing = conn.execute(
                    "SELECT id FROM leads WHERE id = ? AND org_id = ?", (lead.id, org_id)
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM leads WHERE org_id = ? AND company_name = ? AND (website = ? OR contact_email = ?)",
                    (org_id, lead.company_name, lead.website, lead.contact_email),
                ).fetchone()

            if existing:
                lead_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE leads SET
                        campaign_id = ?, website = ?, industry = ?, region = ?,
                        contact_name = ?, contact_role = ?, contact_email = ?,
                        email_verified = ?, company_summary = ?, pain_points = ?,
                        personalization_hook = ?, qualification_score = ?,
                        score_reasoning = ?, language = ?, status = ?,
                        proposal_status = ?, proposal_url = ?, updated_at = ?
                    WHERE id = ? AND org_id = ?
                    """,
                    (
                        lead.campaign_id or 1,
                        lead.website,
                        lead.industry,
                        lead.region,
                        lead.contact_name,
                        lead.contact_role,
                        lead.contact_email,
                        1 if lead.email_verified else 0,
                        lead.company_summary,
                        lead.pain_points,
                        lead.personalization_hook,
                        lead.qualification_score,
                        lead.score_reasoning,
                        lead.language,
                        status_str,
                        lead.proposal_status or "none",
                        lead.proposal_url or "",
                        now,
                        lead_id,
                        org_id,
                    ),
                )
                conn.commit()
                return lead_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO leads (
                        org_id, campaign_id, company_name, website, industry, region,
                        contact_name, contact_role, contact_email, email_verified,
                        company_summary, pain_points, personalization_hook,
                        qualification_score, score_reasoning, language, status,
                        proposal_status, proposal_url, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        org_id,
                        lead.campaign_id or 1,
                        lead.company_name,
                        lead.website,
                        lead.industry,
                        lead.region,
                        lead.contact_name,
                        lead.contact_role,
                        lead.contact_email,
                        1 if lead.email_verified else 0,
                        lead.company_summary,
                        lead.pain_points,
                        lead.personalization_hook,
                        lead.qualification_score,
                        lead.score_reasoning,
                        lead.language,
                        status_str,
                        lead.proposal_status or "none",
                        lead.proposal_url or "",
                        now,
                        now,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid or 0)

    async def get_lead(self, lead_id: int, org_id: Optional[int] = None) -> Optional[Lead]:
        return self._get_lead_sync( lead_id, org_id)

    def _get_lead_sync(self, lead_id: int, org_id: Optional[int] = None) -> Optional[Lead]:
        with self._connect() as conn:
            if org_id is not None:
                row = conn.execute(
                    "SELECT * FROM leads WHERE id = ? AND org_id = ?", (lead_id, org_id)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            return self._row_to_lead(dict(row)) if row else None

    async def get_lead_by_email(
        self, email: str, org_id: Optional[int] = None
    ) -> Optional[Lead]:
        return self._get_lead_by_email_sync( email, org_id)

    def _get_lead_by_email_sync(
        self, email: str, org_id: Optional[int] = None
    ) -> Optional[Lead]:
        with self._connect() as conn:
            if org_id is not None:
                row = conn.execute(
                    "SELECT * FROM leads WHERE LOWER(contact_email) = LOWER(?) AND org_id = ?",
                    (email.strip(), org_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM leads WHERE LOWER(contact_email) = LOWER(?)",
                    (email.strip(),),
                ).fetchone()
            return self._row_to_lead(dict(row)) if row else None

    async def list_leads(
        self, status: Optional[LeadStatus] = None, org_id: Optional[int] = None
    ) -> List[Lead]:
        return self._list_leads_sync( status, org_id)

    def _list_leads_sync(
        self, status: Optional[LeadStatus] = None, org_id: Optional[int] = None
    ) -> List[Lead]:
        with self._connect() as conn:
            query = "SELECT * FROM leads WHERE 1=1"
            params: List[Any] = []
            if org_id is not None:
                query += " AND org_id = ?"
                params.append(org_id)
            if status is not None:
                query += " AND status = ?"
                params.append(status.value)
            query += " ORDER BY qualification_score DESC, id DESC"
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_lead(dict(r)) for r in rows]

    async def update_lead_status(self, lead_id: int, status: LeadStatus) -> None:
        self._update_lead_status_sync( lead_id, status)

    def _update_lead_status_sync(self, lead_id: int, status: LeadStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, utc_now_iso(), lead_id),
            )
            conn.commit()

    @staticmethod
    def _row_to_lead(data: Dict[str, Any]) -> Lead:
        data["email_verified"] = bool(data.get("email_verified", 0))
        data["status"] = LeadStatus(data.get("status", "discovered"))
        return Lead(**data)

    # ==========================================
    # Email Drafts & Outbox Queue CRUD
    # ==========================================
    async def save_email_drafts(self, drafts: List[EmailDraft]) -> List[int]:
        return self._save_email_drafts_sync( drafts)

    def _save_email_drafts_sync(self, drafts: List[EmailDraft]) -> List[int]:
        ids: List[int] = []
        now = utc_now_iso()
        with self._connect() as conn:
            for d in drafts:
                org_id = d.org_id or 1
                conn.execute(
                    "DELETE FROM email_drafts WHERE lead_id = ? AND step_number = ? AND approval_status = 'pending'",
                    (d.lead_id, d.step_number),
                )
                status_val = (
                    d.approval_status.value
                    if isinstance(d.approval_status, ApprovalStatus)
                    else str(d.approval_status)
                )
                cur = conn.execute(
                    """
                    INSERT INTO email_drafts (
                        org_id, lead_id, campaign_id, step_number, subject, body,
                        word_count, language, approval_status, scheduled_at, sent_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        org_id,
                        d.lead_id,
                        d.campaign_id,
                        d.step_number,
                        d.subject,
                        d.body,
                        d.word_count,
                        d.language,
                        status_val,
                        d.scheduled_at,
                        d.sent_at,
                        now,
                    ),
                )
                ids.append(int(cur.lastrowid or 0))
            conn.commit()
        return ids

    async def list_email_drafts(
        self,
        lead_id: Optional[int] = None,
        approval_status: Optional[ApprovalStatus] = None,
        org_id: Optional[int] = None,
    ) -> List[EmailDraft]:
        return self._list_email_drafts_sync( lead_id, approval_status, org_id
        )

    def _list_email_drafts_sync(
        self,
        lead_id: Optional[int] = None,
        approval_status: Optional[ApprovalStatus] = None,
        org_id: Optional[int] = None,
    ) -> List[EmailDraft]:
        with self._connect() as conn:
            query = "SELECT * FROM email_drafts WHERE 1=1"
            params: List[Any] = []
            if org_id is not None:
                query += " AND org_id = ?"
                params.append(org_id)
            if lead_id is not None:
                query += " AND lead_id = ?"
                params.append(lead_id)
            if approval_status is not None:
                query += " AND approval_status = ?"
                params.append(approval_status.value)
            query += " ORDER BY lead_id ASC, step_number ASC"
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_draft(dict(r)) for r in rows]

    async def update_draft_approval(
        self,
        draft_id: int,
        status: ApprovalStatus,
        scheduled_at: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> None:
        self._update_draft_approval_sync(
            draft_id,
            status,
            scheduled_at,
            subject,
            body,
        )

    def _update_draft_approval_sync(
        self,
        draft_id: int,
        status: ApprovalStatus,
        scheduled_at: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            if subject is not None and body is not None:
                word_count = len(body.split())
                conn.execute(
                    """
                    UPDATE email_drafts
                    SET approval_status = ?, scheduled_at = COALESCE(?, scheduled_at),
                        subject = ?, body = ?, word_count = ?
                    WHERE id = ?
                    """,
                    (status.value, scheduled_at, subject, body, word_count, draft_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE email_drafts
                    SET approval_status = ?, scheduled_at = COALESCE(?, scheduled_at)
                    WHERE id = ?
                    """,
                    (status.value, scheduled_at, draft_id),
                )
            conn.commit()

    async def mark_draft_sent(self, draft_id: int) -> None:
        self._mark_draft_sent_sync( draft_id)

    def _mark_draft_sent_sync(self, draft_id: int) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE email_drafts SET approval_status = ?, sent_at = ? WHERE id = ?",
                (ApprovalStatus.SENT.value, now, draft_id),
            )
            conn.commit()

    async def cancel_pending_drafts_for_lead(self, lead_id: int) -> int:
        return self._cancel_pending_drafts_sync( lead_id)

    def _cancel_pending_drafts_sync(self, lead_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE email_drafts
                SET approval_status = ?
                WHERE lead_id = ? AND approval_status IN ('pending', 'approved') AND sent_at IS NULL
                """,
                (ApprovalStatus.CANCELLED.value, lead_id),
            )
            conn.commit()
            return cur.rowcount

    async def count_sent_today(self, org_id: Optional[int] = None) -> int:
        return self._count_sent_today_sync( org_id)

    def _count_sent_today_sync(self, org_id: Optional[int] = None) -> int:
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            if org_id is not None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM email_drafts WHERE org_id = ? AND approval_status = 'sent' AND sent_at LIKE ?",
                    (org_id, f"{today_prefix}%"),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM email_drafts WHERE approval_status = 'sent' AND sent_at LIKE ?",
                    (f"{today_prefix}%",),
                ).fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    def _row_to_draft(data: Dict[str, Any]) -> EmailDraft:
        data["approval_status"] = ApprovalStatus(data.get("approval_status", "pending"))
        return EmailDraft(**data)

    # ==========================================
    # Inbox Replies CRUD
    # ==========================================
    async def save_reply(self, reply: InboxReply) -> int:
        return self._save_reply_sync( reply)

    def _save_reply_sync(self, reply: InboxReply) -> int:
        now = reply.received_at or utc_now_iso()
        org_id = reply.org_id or 1
        intent_val = (
            reply.intent.value if isinstance(reply.intent, ReplyIntent) else str(reply.intent)
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO inbox_replies (
                    org_id, lead_id, from_email, subject, body, intent,
                    confidence, ai_suggested_reply, reply_approved, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    reply.lead_id,
                    reply.from_email,
                    reply.subject,
                    reply.body,
                    intent_val,
                    reply.confidence,
                    reply.ai_suggested_reply,
                    1 if reply.reply_approved else 0,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid or 0)

    async def list_replies(self, org_id: Optional[int] = None) -> List[InboxReply]:
        return self._list_replies_sync( org_id)

    def _list_replies_sync(self, org_id: Optional[int] = None) -> List[InboxReply]:
        with self._connect() as conn:
            if org_id is not None:
                rows = conn.execute(
                    "SELECT * FROM inbox_replies WHERE org_id = ? ORDER BY id DESC", (org_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM inbox_replies ORDER BY id DESC").fetchall()
            result: List[InboxReply] = []
            for r in rows:
                d = dict(r)
                d["intent"] = ReplyIntent(d.get("intent", "question"))
                d["reply_approved"] = bool(d.get("reply_approved", 0))
                result.append(InboxReply(**d))
            return result

    # ==========================================
    # Interactive Proposals CRUD (Unified Engine)
    # ==========================================
    async def save_proposal(self, proposal: InteractiveProposal) -> int:
        return self._save_proposal_sync( proposal)

    def _save_proposal_sync(self, proposal: InteractiveProposal) -> int:
        now = utc_now_iso()
        proposal.updated_at = now
        if not proposal.created_at:
            proposal.created_at = now

        payload_json = json.dumps(proposal.model_dump(), ensure_ascii=False)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM proposals WHERE slug = ?", (proposal.slug,)
            ).fetchone()
            if existing:
                prop_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE proposals SET
                        org_id = ?, lead_id = ?, title_ar = ?, title_en = ?,
                        client_company = ?, client_contact = ?, client_role = ?,
                        industry = ?, language = ?, template_id = ?, proposal_json = ?,
                        total_amount = ?, currency = ?, white_label = ?, status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        proposal.org_id,
                        proposal.lead_id,
                        proposal.title_ar,
                        proposal.title_en,
                        proposal.client_company,
                        proposal.client_contact,
                        proposal.client_role,
                        proposal.industry,
                        proposal.language,
                        proposal.template_id,
                        payload_json,
                        proposal.total_amount,
                        proposal.currency,
                        1 if proposal.white_label else 0,
                        proposal.status,
                        now,
                        prop_id,
                    ),
                )
                conn.commit()
                return prop_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO proposals (
                        org_id, lead_id, slug, title_ar, title_en,
                        client_company, client_contact, client_role, industry,
                        language, template_id, proposal_json, total_amount,
                        currency, white_label, status, views_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.org_id,
                        proposal.lead_id,
                        proposal.slug,
                        proposal.title_ar,
                        proposal.title_en,
                        proposal.client_company,
                        proposal.client_contact,
                        proposal.client_role,
                        proposal.industry,
                        proposal.language,
                        proposal.template_id,
                        payload_json,
                        proposal.total_amount,
                        proposal.currency,
                        1 if proposal.white_label else 0,
                        proposal.status,
                        proposal.views_count,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid or 0)

    async def get_proposal_by_slug(
        self, slug: str, increment_view: bool = False
    ) -> Optional[InteractiveProposal]:
        return self._get_proposal_by_slug_sync( slug, increment_view)

    def _get_proposal_by_slug_sync(
        self, slug: str, increment_view: bool = False
    ) -> Optional[InteractiveProposal]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proposals WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return None
            if increment_view:
                conn.execute(
                    "UPDATE proposals SET views_count = views_count + 1, status = CASE WHEN status = 'generated' THEN 'viewed' ELSE status END WHERE id = ?",
                    (row["id"],),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone()
            return self._row_to_proposal(dict(row))

    async def accept_proposal_by_slug(self, slug: str, accepted_by: str) -> Optional[InteractiveProposal]:
        return self._accept_proposal_by_slug_sync( slug, accepted_by)

    def _accept_proposal_by_slug_sync(self, slug: str, accepted_by: str) -> Optional[InteractiveProposal]:
        now = utc_now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proposals WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE proposals SET status = 'accepted', accepted_at = ?, accepted_by = ?, updated_at = ? WHERE id = ?",
                (now, accepted_by.strip(), now, row["id"]),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone()
            return self._row_to_proposal(dict(updated))

    async def list_proposals(self, org_id: Optional[int] = None) -> List[InteractiveProposal]:
        return self._list_proposals_sync( org_id)

    def _list_proposals_sync(self, org_id: Optional[int] = None) -> List[InteractiveProposal]:
        with self._connect() as conn:
            if org_id is not None:
                rows = conn.execute(
                    "SELECT * FROM proposals WHERE org_id = ? ORDER BY id DESC", (org_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM proposals ORDER BY id DESC").fetchall()
            return [self._row_to_proposal(dict(r)) for r in rows]

    @staticmethod
    def _row_to_proposal(row_dict: Dict[str, Any]) -> InteractiveProposal:
        data = json.loads(row_dict.get("proposal_json") or "{}")
        data["id"] = row_dict["id"]
        data["org_id"] = row_dict["org_id"]
        data["slug"] = row_dict["slug"]
        data["status"] = row_dict["status"]
        data["views_count"] = row_dict["views_count"]
        data["accepted_at"] = row_dict.get("accepted_at")
        data["accepted_by"] = row_dict.get("accepted_by", "")
        data["white_label"] = bool(row_dict.get("white_label", 0))
        return InteractiveProposal(**data)
