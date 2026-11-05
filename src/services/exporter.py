"""Exporter service (`sales-agent export`): Exports leads and sequences to CSV or JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from src.core.database import DatabaseManager


class CampaignExporter:
    """Exports enriched prospects and their 3-step email sequences into sequencer-ready CSV/JSON."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    async def export_to_csv(self, output_path: str = "data/exports/sequencer_export.csv") -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        rows = await self._build_export_rows()
        fieldnames = [
            "lead_id",
            "company_name",
            "website",
            "industry",
            "region",
            "contact_name",
            "contact_role",
            "contact_email",
            "email_verified",
            "qualification_score",
            "status",
            "proposal_status",
            "proposal_url",
            "language",
            "personalization_hook",
            "step_1_subject",
            "step_1_body",
            "step_2_subject",
            "step_2_body",
            "step_3_subject",
            "step_3_body",
        ]

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        return path

    async def export_to_json(self, output_path: str = "data/exports/sequencer_export.json") -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = await self._build_export_rows()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        return path

    async def _build_export_rows(self) -> List[Dict[str, Any]]:
        leads = await self.db.list_leads()
        all_drafts = await self.db.list_email_drafts()

        drafts_by_lead: Dict[int, Dict[int, Any]] = {}
        for d in all_drafts:
            drafts_by_lead.setdefault(d.lead_id, {})[d.step_number] = d

        export_rows: List[Dict[str, Any]] = []
        for lead in leads:
            lid = int(lead.id or 0)
            lead_drafts = drafts_by_lead.get(lid, {})
            s1 = lead_drafts.get(1)
            s2 = lead_drafts.get(2)
            s3 = lead_drafts.get(3)

            export_rows.append(
                {
                    "lead_id": lid,
                    "company_name": lead.company_name,
                    "website": lead.website,
                    "industry": lead.industry,
                    "region": lead.region,
                    "contact_name": lead.contact_name,
                    "contact_role": lead.contact_role,
                    "contact_email": lead.contact_email,
                    "email_verified": lead.email_verified,
                    "qualification_score": lead.qualification_score,
                    "status": lead.status.value,
                    "proposal_status": getattr(lead, "proposal_status", "none"),
                    "proposal_url": getattr(lead, "proposal_url", ""),
                    "language": lead.language,
                    "personalization_hook": lead.personalization_hook,
                    "step_1_subject": s1.subject if s1 else "",
                    "step_1_body": s1.body if s1 else "",
                    "step_2_subject": s2.subject if s2 else "",
                    "step_2_body": s2.body if s2 else "",
                    "step_3_subject": s3.subject if s3 else "",
                    "step_3_body": s3.body if s3 else "",
                }
            )
        return export_rows
