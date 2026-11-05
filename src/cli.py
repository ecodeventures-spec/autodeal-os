"""Command-Line Interface (`sales-agent`) for managing the AI sales pipeline."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import List, Optional

import uvicorn

from src.core.orchestrator import SalesOrchestrator


def _print_banner(title: str, subtitle: str = "") -> None:
    line = "=" * 72
    print(f"\n{line}")
    print(f"  {title}")
    if subtitle:
        print(f"  {subtitle}")
    print(f"{line}")


async def _handle_async_command(args: argparse.Namespace) -> None:
    orchestrator = SalesOrchestrator()
    await orchestrator.initialize()

    cmd = args.command

    if cmd == "run":
        _print_banner(
            "🚀 تشغيل دورة المبيعات الكاملة (sales-agent)",
            f"اللغة: {args.lang} | العدد: {args.limit} | اعتماد تلقائي: {args.auto_approve}",
        )
        result = await orchestrator.run_full_pipeline(
            language=args.lang,
            limit=args.limit,
            auto_approve=args.auto_approve,
        )
        print(
            f"✅ تم اكتشاف {result['discovered_count']} شركات، "
            f"تأهيل {result['qualified_count']} عملاء، "
            f"وصياغة {result['drafts_created']} رسالة بريد."
        )
        await _print_status_tables(orchestrator)

    elif cmd == "scout":
        discovered = await orchestrator.scout.run(
            industry=args.industry,
            region=args.region,
            language=args.lang,
            limit=args.limit,
            csv_path=args.csv,
        )
        ids = [int(l.id) for l in discovered if l.id is not None]
        enriched = await orchestrator.enricher.run(lead_ids=ids)
        print(f"🔍 تم استكشاف وتقييم {len(enriched)} عملاء بنجاح.")
        await _print_status_tables(orchestrator)

    elif cmd == "write":
        drafts = await orchestrator.writer.run()
        print(f"✍️ تم كتابة {len(drafts)} مسودة بريد وإضافتها إلى سلم الموافقات.")

    elif cmd == "approve":
        count = await orchestrator.approve_all_pending()
        print(f"✅ تم اعتماد {count} مسودة بريد للإرسال.")

    elif cmd == "send":
        res = await orchestrator.sender.run()
        print(
            f"📤 تم إرسال {res['sent_count']} رسالة "
            f"(وضع المحاكاة Dry-Run: {res['dry_run']})."
        )

    elif cmd == "reply":
        leads = await orchestrator.db.list_leads()
        default_email = leads[0].contact_email if leads else "khalid@namaacloud.sa"
        email_addr = args.email or default_email
        replies = await orchestrator.handler.run(
            simulated_replies=[
                {
                    "from_email": email_addr,
                    "subject": "Re: تواصل بخصوص الأتمتة",
                    "body": args.text,
                }
            ]
        )
        for r in replies:
            _print_banner(
                f"📥 معالج الردود (Handler Agent) | من: {r.from_email}",
                f"النية المصنفة: {r.intent.value} ({int(r.confidence * 100)}%)",
            )
            print("الرد المقترح لحجز الاجتماع:\n")
            print(r.ai_suggested_reply)
            print("-" * 72)

    elif cmd == "export":
        csv_path = await orchestrator.exporter.export_to_csv(args.output)
        json_path = await orchestrator.exporter.export_to_json()
        print(f"📁 تم تصدير ملف CSV بنجاح إلى: {csv_path}")
        print(f"📁 تم تصدير ملف JSON بنجاح إلى: {json_path}")

    elif cmd == "proposal":
        lead_id = args.lead_id
        transcript_raw = args.transcript or ""
        
        # Check if transcript is a file path
        from pathlib import Path
        p_path = Path(transcript_raw)
        if p_path.exists() and p_path.is_file():
            transcript_content = p_path.read_text(encoding="utf-8")
        elif not transcript_raw.strip():
            transcript_content = (
                "مكالمة زوم مع العميل: نوقش فيها احتياجهم لنشر محطات الخدمة الذاتية في 3 مواقع حيوية. "
                "العميل أبدى اهتماماً كبيراً بـ خفض تكلفة التشغيل بنسبة 35% والتوسع السريع دون الحاجة لموظفين إضافيين. "
                "الميزانية المتاحة تغطي شراء دفعة أولى من جهازين مع الرغبة في الدفع على 3 مراحل (50% مقدم، 40% قبل الشحن، 10% بعد التشغيل). "
                "العميل طلب ضمان لمدة سنتين مع توفير قطع الغيار وخدمة الصيانة والدعم الفني السريع."
            )
        else:
            transcript_content = transcript_raw

        print(f"⚡ جاري تحليل تفريغ الاجتماع واستخراج مواصفات العرض للعميل [{lead_id}]...")
        result = await orchestrator.generate_proposal_for_lead(
            lead_id=lead_id,
            transcript_text=transcript_content,
            custom_notes=args.notes or "",
        )

        tpl = result["matched_template"]
        spec = result["spec"]
        urls = result["proposal_urls"]

        _print_banner(
            f"🎯 تم إنشاء العرض الفني والمالي التفاعلي بنجاح | {result['ref_code']}",
            f"الشركة: {result['company_name']} | القالب: {tpl['name_ar']} ({tpl['segment_code']})",
        )
        print(f"🔗 رابط العرض المحلي (Proposals Engine): {urls['local_url']}")
        print(f"🌐 رابط النشر السحابي (Production):       {urls['production_url']}")
        print(f"💰 التكلفة الإجمالية المقترحة:          {spec.get('total_price_sar', tpl['unit_price_sar']):,} ريال سعودي")
        print(f"📦 عدد المحطات / الأجهزة:                {spec.get('units_count', 1)} جهاز")
        print(f"💳 شروط الدفع المعتمدة:                  {spec.get('payment_terms_ar', '')}")
        print(f"⏱️ مدة التوريد والجاهزية:               {spec.get('delivery_weeks', 6)} أسابيع")
        print("\n" + "=" * 72)
        print("✉️ مسودة إيميل المتابعة التنفيذي المضافة إلى سلم الموافقات (Step 4):\n")
        print(f"الموضوع: {spec.get('follow_up_email_subject', '')}")
        print("-" * 72)
        print(spec.get("follow_up_email_body", ""))
        print("=" * 72)
        print("\n💡 يمكنك اعتماد الإيميل وإرساله فوراً عبر الأمر: python -m src.cli approve ثم python -m src.cli send")

    elif cmd == "status":
        await _print_status_tables(orchestrator)


async def _print_status_tables(orchestrator: SalesOrchestrator) -> None:
    analytics = await orchestrator.analyst.run()
    leads = await orchestrator.db.list_leads()

    _print_banner("📊 قائمة العملاء المحتملين وتقييم المطابقة (Leads & ICP Scores)")
    for l in leads:
        prop_str = f" | 📑 العرض: {l.proposal_url}" if l.proposal_status == "generated" and l.proposal_url else ""
        print(
            f"  [{l.id}] {l.company_name} | {l.contact_name} <{l.contact_email}> "
            f"| ICP: {l.qualification_score}/100 | الحالة: {l.status.value}{prop_str}"
        )

    print("\n" + "-" * 72)
    print(
        f"📈 ملخص الأداء: إجمالي العملاء: {analytics['total_leads']} | "
        f"متوسط التقييم: {analytics['average_icp_score']}% | "
        f"بانتظار الموافقة: {analytics['drafts_pending_approval']} | "
        f"المرسلة: {analytics['emails_sent']} | "
        f"اجتماعات محجوزة: {analytics['meetings_booked']}"
    )
    print("-" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sales-agent",
        description="Autonomous Multi-Agent B2B AI Outbound Sales Platform",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run end-to-end discovery, enrichment, and writing pipeline")
    p_run.add_argument("--lang", default="ar", choices=["ar", "en", "both"], help="Campaign language")
    p_run.add_argument("--limit", type=int, default=4, help="Number of prospects to process")
    p_run.add_argument("--auto-approve", action="store_true", help="Approve and send step 1 immediately")

    p_scout = sub.add_parser("scout", help="Discover and enrich prospects")
    p_scout.add_argument("--industry", default=None, help="Target industry filter")
    p_scout.add_argument("--region", default=None, help="Target region filter")
    p_scout.add_argument("--lang", default="ar", choices=["ar", "en", "both"])
    p_scout.add_argument("--limit", type=int, default=4)
    p_scout.add_argument("--csv", default=None, help="Import prospects from CSV path")

    sub.add_parser("write", help="Generate 3-step email sequences for enriched leads")
    sub.add_parser("approve", help="Approve all pending email drafts in the Approval Ladder")
    sub.add_parser("send", help="Dispatch approved emails from outbox queue")

    p_reply = sub.add_parser("reply", help="Simulate or process an incoming prospect reply")
    p_reply.add_argument("--email", default=None, help="Sender email address")
    p_reply.add_argument(
        "--text",
        default="مرحباً، نعم نحن مهتمون جداً بمعرفة التفاصيل وحجز موعد لاجتماع سريع هذا الأسبوع.",
        help="Reply body text",
    )

    p_proposal = sub.add_parser("proposal", help="Bridge Zoom transcript into Makaaen Proposal and follow-up email")
    p_proposal.add_argument("--lead-id", type=int, required=True, help="Target lead ID")
    p_proposal.add_argument("--transcript", default="", help="Transcript text or path to .txt transcript file")
    p_proposal.add_argument("--notes", default="", help="Additional account executive notes")

    p_export = sub.add_parser("export", help="Export leads and sequences to CSV/JSON")
    p_export.add_argument("--output", default="data/exports/sequencer_export.csv")

    sub.add_parser("status", help="Show pipeline analytics and lead status table")

    p_dash = sub.add_parser("dashboard", help="Launch interactive Web Dashboard")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dashboard":
        print(f"🌐 تشغيل لوحة التحكم التفاعلية على الرابط: http://{args.host}:{args.port}")
        uvicorn.run("src.api.server:app", host=args.host, port=args.port, reload=False)
    else:
        asyncio.run(_handle_async_command(args))


if __name__ == "__main__":
    main()
