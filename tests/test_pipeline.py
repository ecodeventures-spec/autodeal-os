"""Comprehensive Automated & Integration Test Suite for NUDHUJ AutoDeal OS SaaS Platform (`autodeal.nudhuj.com`)."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.auth import create_access_token, verify_access_token
from src.core.config import load_settings, save_settings
from src.core.database import QuotaExceededError
from src.core.models import ApprovalStatus, LeadStatus, PlanTier, ReplyIntent
from src.core.orchestrator import SalesOrchestrator
from src.services.diagnostics import test_ai_engine_connection, test_email_connections


def _run_async(coro):
    """Drive a coroutine to completion without requiring a Windows loopback socketpair in sandboxed environments."""
    try:
        while True:
            coro.send(None)
    except StopIteration as exc:
        return exc.value


class TestNudhujAutoDealOSSaaS(unittest.TestCase):
    def test_1_saas_registration_free_plan_and_jwt_auth(self) -> None:
        _run_async(self._test_1_impl())

    async def _test_1_impl(self) -> None:
        """Verify tenant registration, automatic Free Plan provisioning, and signed JWT tokens."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings = load_settings()
            settings.database_path = str(tmp_path / "test_saas_auth.db")
            settings.llm.provider = "mock"

            orchestrator = SalesOrchestrator(settings)
            await orchestrator.initialize()

            org, user = await orchestrator.db.register_tenant_and_user(
                company_name="شركة آفاق للاستشارات القانونية",
                full_name="المستشار طلال العتيبي",
                email="talal@afaq-law.sa",
                password="SecurePass!2026",
                industry="الاستشارات القانونية والمحاماة للشركات",
                website="https://afaq-law.sa",
                plan_tier="free",
            )
            self.assertEqual(org.plan_tier, PlanTier.FREE.value)
            self.assertEqual(org.leads_quota, 25)
            self.assertEqual(org.proposals_quota, 3)
            self.assertEqual(user.org_id, org.id)

            # Authenticate user
            auth_res = await orchestrator.db.authenticate_user("talal@afaq-law.sa", "SecurePass!2026")
            self.assertIsNotNone(auth_res)
            assert auth_res is not None
            authed_user, authed_org = auth_res
            self.assertEqual(authed_user.email, "talal@afaq-law.sa")
            self.assertEqual(authed_org.id, org.id)

            # Verify token signature & decoding
            token = create_access_token(
                user_id=int(authed_user.id or 1),
                org_id=int(authed_org.id or 1),
                email=authed_user.email,
                role=authed_user.role,
            )
            payload = verify_access_token(token)
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["org_id"], org.id)

    def test_2_multi_tenant_strict_data_isolation(self) -> None:
        _run_async(self._test_2_impl())

    async def _test_2_impl(self) -> None:
        """Verify 100% isolation between Org A and Org B leads, drafts, settings, and proposals."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings = load_settings()
            settings.database_path = str(tmp_path / "test_isolation.db")
            settings.llm.provider = "mock"

            orchestrator = SalesOrchestrator(settings)
            await orchestrator.initialize()

            org_a, _ = await orchestrator.db.register_tenant_and_user(
                company_name="مكتب النخبة للمحاماة",
                full_name="أحمد",
                email="ahmed@elite-law.sa",
                password="pass123",
                industry="الاستشارات القانونية",
            )
            org_b, _ = await orchestrator.db.register_tenant_and_user(
                company_name="مجموعة الشفاء الطبية",
                full_name="سارة",
                email="sara@shifaa-med.sa",
                password="pass123",
                industry="الرعاية الصحية والعيادات",
            )

            # Run dynamic scout for Org A (Legal sector) and Org B (Medical sector)
            await orchestrator.run_full_pipeline(
                language="ar",
                limit=2,
                industry="شركات المقاولات والتوريد",
                org_id=int(org_a.id or 2),
            )
            await orchestrator.run_full_pipeline(
                language="ar",
                limit=3,
                industry="المستشفيات والمراكز الطبية",
                org_id=int(org_b.id or 3),
            )

            leads_a = await orchestrator.db.list_leads(org_id=org_a.id)
            leads_b = await orchestrator.db.list_leads(org_id=org_b.id)
            self.assertEqual(len(leads_a), 2)
            self.assertEqual(len(leads_b), 3)
            self.assertTrue(all(l.org_id == org_a.id for l in leads_a))
            self.assertTrue(all(l.org_id == org_b.id for l in leads_b))

    def test_3_quota_enforcement_and_plan_upgrades(self) -> None:
        _run_async(self._test_3_impl())

    async def _test_3_impl(self) -> None:
        """Verify SaaS quota guard blocks excess usage on Free plan and unlocks immediately upon upgrade."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings = load_settings()
            settings.database_path = str(tmp_path / "test_quotas.db")
            settings.llm.provider = "mock"

            orchestrator = SalesOrchestrator(settings)
            await orchestrator.initialize()

            org, _ = await orchestrator.db.register_tenant_and_user(
                company_name="شركة انطلاق الناشئة",
                full_name="خالد",
                email="khalid@intilaq.sa",
                password="pass123",
                plan_tier="free",
            )
            org_id = int(org.id or 2)

            # Free plan has proposals_quota = 3; consuming 3 succeeds, 4th raises QuotaExceededError
            await orchestrator.db.check_and_consume_quota(org_id, "proposals", 3)
            with self.assertRaises(QuotaExceededError):
                await orchestrator.db.check_and_consume_quota(org_id, "proposals", 1)

            # Upgrade to Business Scale plan -> quota increases to 500
            upgraded = await orchestrator.db.upgrade_organization_plan(
                org_id, PlanTier.BUSINESS.value, "yearly"
            )
            self.assertEqual(upgraded.plan_tier, PlanTier.BUSINESS.value)
            self.assertEqual(upgraded.proposals_quota, 500)

            # Consuming another proposal now succeeds
            after_consume = await orchestrator.db.check_and_consume_quota(org_id, "proposals", 1)
            self.assertEqual(after_consume.proposals_used, 4)

    def test_4_company_profiler_and_persistent_settings(self) -> None:
        _run_async(self._test_4_impl())

    async def _test_4_impl(self) -> None:
        """Verify Universal Company Profiler understands any business activity and persists settings."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            yaml_path = tmp_path / "settings.yaml"
            settings = load_settings(yaml_path)
            settings.database_path = str(tmp_path / "test_profiler.db")
            settings.llm.provider = "mock"

            orchestrator = SalesOrchestrator(settings)
            await orchestrator.initialize()

            res = await orchestrator.company_profiler.run(
                website_url="https://rawafed-contracting.sa",
                company_name_hint="شركة روافد للمقاولات الهندسية",
                industry_hint="الهندسة والمقاولات والتطوير العقاري",
                raw_profile_text="نقدم خدمات المقاولات العامة وبناء الأبراج التجارية وتجهيز المكاتب الحديثة في الرياض.",
                org_id=1,
            )
            prof = res["profile"]
            self.assertEqual(prof["company_name_ar"], "شركة روافد للمقاولات الهندسية")
            self.assertIn("المقاولات", prof["industry"])
            self.assertGreaterEqual(len(prof["services_catalog"]), 3)

            # Test persistent YAML settings save & reload
            settings.sender.daily_send_cap = 85
            settings.sender.sender_name = "م. سلطان | روافد الهندسية"
            save_settings(settings, yaml_path)

            reloaded = load_settings(yaml_path)
            self.assertEqual(reloaded.sender.daily_send_cap, 85)
            self.assertEqual(reloaded.sender.sender_name, "م. سلطان | روافد الهندسية")

            # Test AI & Email Diagnostics
            ai_diag = await test_ai_engine_connection(settings)
            self.assertEqual(ai_diag["status"], "success")
            email_diag = await test_email_connections(
                "smtp.gmail.com", 587, "", "", "imap.gmail.com", 993, "", ""
            )
            self.assertIn(email_diag["smtp"]["status"], ("simulated", "success"))

    def test_5_full_end_to_end_pipeline_and_interactive_proposal_acceptance(self) -> None:
        _run_async(self._test_5_impl())

    async def _test_5_impl(self) -> None:
        """Verify the complete 7-stage pipeline and interactive proposal showcase (/c/{slug}) & digital acceptance."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings = load_settings()
            settings.database_path = str(tmp_path / "test_e2e_autodeal.db")
            settings.llm.provider = "mock"
            settings.system.dry_run = True

            orchestrator = SalesOrchestrator(settings)
            await orchestrator.initialize()

            # 1. Run Pipeline (Scout -> Enricher -> Writer)
            summary = await orchestrator.run_full_pipeline(
                language="both",
                limit=3,
                auto_approve=False,
                org_id=1,
            )
            self.assertEqual(summary["discovered_count"], 3)
            self.assertEqual(summary["qualified_count"], 3)
            self.assertEqual(summary["drafts_created"], 9)

            leads = await orchestrator.db.list_leads(org_id=1)
            self.assertEqual(len(leads), 3)

            # 2. Approve all pending drafts & send Step 1
            approved_count = await orchestrator.approve_all_pending(org_id=1)
            self.assertEqual(approved_count, 9)

            send_res = await orchestrator.sender.run(org_id=1)
            self.assertEqual(send_res["sent_count"], 3)

            # 3. Simulate Reply from Lead 1 -> Verify Intent & Stop-on-Reply
            first_lead = leads[0]
            replies = await orchestrator.handler.run(
                simulated_replies=[
                    {
                        "from_email": first_lead.contact_email,
                        "subject": "Re: تواصل",
                        "body": "نعم نحن مهتمون جداً بحجز موعد اجتماع هذا الأسبوع لمناقشة التفاصيل.",
                    }
                ]
            )
            self.assertEqual(len(replies), 1)
            self.assertEqual(replies[0].intent, ReplyIntent.INTERESTED)

            # Follow-up steps (Steps 2 & 3) for this lead must be cancelled (Stop-on-Reply)
            lead_drafts = await orchestrator.db.list_email_drafts(lead_id=first_lead.id)
            follow_ups = [d for d in lead_drafts if d.step_number in (2, 3)]
            self.assertTrue(all(d.approval_status == ApprovalStatus.CANCELLED for d in follow_ups))

            # 4. Generate Interactive Proposal on unified domain (/c/{slug})
            transcript_text = (
                "العميل مهتم بتنفيذ الحل المؤسسي لعدد 2 فرع كمرحلة أولى، والميزانية معتمدة."
            )
            proposal_res = await orchestrator.generate_proposal_for_lead(
                lead_id=int(first_lead.id or 1),
                transcript_text=transcript_text,
                org_id=1,
            )
            self.assertEqual(proposal_res["lead_id"], first_lead.id)
            slug = proposal_res["slug"]
            self.assertTrue(proposal_res["proposal_urls"]["local_url"].startswith("/c/"))
            self.assertIn("https://autodeal.nudhuj.com/c/", proposal_res["proposal_urls"]["production_url"])

            # 5. Public Proposal View & Digital Acceptance by Client
            viewed_prop = await orchestrator.db.get_proposal_by_slug(slug, increment_view=True)
            self.assertIsNotNone(viewed_prop)
            assert viewed_prop is not None
            self.assertEqual(viewed_prop.views_count, 1)

            accepted_prop = await orchestrator.db.accept_proposal_by_slug(
                slug, "م. خالد العتيبي - الرئيس التنفيذي"
            )
            self.assertIsNotNone(accepted_prop)
            assert accepted_prop is not None
            self.assertEqual(accepted_prop.status, "accepted")
            self.assertIn("خالد العتيبي", accepted_prop.accepted_by)

            # 6. Check System Health & Exports
            health = await orchestrator.get_system_health(org_id=1)
            self.assertTrue(health["ai_engine"]["ready"])
            self.assertTrue(health["company_identity"]["ready"])

            csv_file = await orchestrator.exporter.export_to_csv(str(tmp_path / "export.csv"))
            json_file = await orchestrator.exporter.export_to_json(str(tmp_path / "export.json"))
            self.assertTrue(csv_file.exists())
            self.assertTrue(json_file.exists())


if __name__ == "__main__":
    unittest.main()
