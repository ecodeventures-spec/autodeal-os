"""Analyst Agent: Computes pipeline telemetry, conversion metrics, and strategic recommendations per tenant."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from src.agents.base import BaseSalesAgent
from src.core.models import ApprovalStatus


class AnalystAgent(BaseSalesAgent):
    """
    Crunches pipeline statistics, lead qualification scores, email approval/send rates,
    proposals generated, and reply intent distribution scoped to a tenant (`org_id`).
    """

    async def run(self, org_id: Optional[int] = None) -> Dict[str, Any]:
        leads = await self.db.list_leads(org_id=org_id)
        drafts = await self.db.list_email_drafts(org_id=org_id)
        replies = await self.db.list_replies(org_id=org_id)
        proposals = await self.db.list_proposals(org_id=org_id)

        total_leads = len(leads)
        status_counts = Counter(l.status.value for l in leads)
        avg_score = (
            round(sum(l.qualification_score for l in leads) / total_leads, 1)
            if total_leads > 0
            else 0.0
        )

        draft_status_counts = Counter(d.approval_status.value for d in drafts)
        total_sent = draft_status_counts.get(ApprovalStatus.SENT.value, 0)
        total_pending_approval = draft_status_counts.get(ApprovalStatus.PENDING.value, 0)
        total_approved_queued = draft_status_counts.get(ApprovalStatus.APPROVED.value, 0)

        intent_counts = Counter(r.intent.value for r in replies)
        total_replies = len(replies)

        reply_rate = round((total_replies / max(1, total_sent)) * 100, 1) if total_sent > 0 else 0.0
        positive_replies = intent_counts.get("interested", 0)
        meeting_rate = round((positive_replies / max(1, total_leads)) * 100, 1) if total_leads > 0 else 0.0
        total_proposals_value = round(sum(p.total_amount for p in proposals), 2)

        recommendations: List[str] = []
        if total_leads == 0:
            recommendations.append("ابدأ بتعريف هوية شركتك أو تشغيل وكيل الاستكشاف (Scout) لإضافة عملاء محتملين.")
        if total_pending_approval > 0:
            recommendations.append(
                f"يوجد {total_pending_approval} مسودة بريد بانتظار موافقتك في سلم الموافقات (Approval Ladder)."
            )
        if total_approved_queued > 0:
            recommendations.append(
                f"يوجد {total_approved_queued} رسالة معتمدة جاهزة للإرسال عبر وكيل الإرسال (Sender)."
            )
        if positive_replies > 0:
            recommendations.append(
                f"تم تسجيل {positive_replies} عميل مهتم! يمكنك إصدار عرض فني ومالي تفاعلي فوري لهم."
            )
        if not recommendations:
            recommendations.append("النظام يعمل بكفاءة عالية. يمكنك تفعيل الطيار الآلي أو توسيع نطاق الاستكشاف.")

        return {
            "total_leads": total_leads,
            "average_icp_score": avg_score,
            "lead_status_breakdown": dict(status_counts),
            "total_drafts": len(drafts),
            "drafts_pending_approval": total_pending_approval,
            "drafts_approved_queued": total_approved_queued,
            "emails_sent": total_sent,
            "total_replies": total_replies,
            "reply_rate_percent": reply_rate,
            "meetings_booked": status_counts.get("meeting_booked", 0),
            "meeting_conversion_percent": meeting_rate,
            "proposals_count": len(proposals),
            "proposals_total_value": total_proposals_value,
            "intent_distribution": dict(intent_counts),
            "recommendations": recommendations,
        }
