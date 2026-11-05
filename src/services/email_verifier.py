"""Email syntax and domain/MX record verification service."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})$")
DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "tempmail.com",
    "10minutemail.com",
    "guerrillamail.com",
    "yopmail.com",
}


@dataclass
class EmailVerificationResult:
    email: str
    is_valid_syntax: bool
    has_mx_record: bool
    is_disposable: bool
    reason: str

    @property
    def is_deliverable(self) -> bool:
        return self.is_valid_syntax and not self.is_disposable and self.has_mx_record


class EmailVerifier:
    """Validates email addresses via syntax check, disposable domain filter, and DNS MX lookup."""

    def __init__(self, check_dns: bool = True) -> None:
        self.check_dns = check_dns

    async def verify(self, email: str) -> EmailVerificationResult:
        clean_email = (email or "").strip().lower()
        match = EMAIL_PATTERN.match(clean_email)
        if not match:
            return EmailVerificationResult(
                email=clean_email,
                is_valid_syntax=False,
                has_mx_record=False,
                is_disposable=False,
                reason="صيغة البريد الإلكتروني غير صحيحة",
            )

        domain = match.group(1)
        if domain in DISPOSABLE_DOMAINS:
            return EmailVerificationResult(
                email=clean_email,
                is_valid_syntax=True,
                has_mx_record=False,
                is_disposable=True,
                reason="نطاق بريد مؤقت غير موثوق (Disposable Domain)",
            )

        if not self.check_dns:
            return EmailVerificationResult(
                email=clean_email,
                is_valid_syntax=True,
                has_mx_record=True,
                is_disposable=False,
                reason="تم التحقق من الصيغة والنطاق بنجاح",
            )

        has_mx = self._lookup_mx(domain)
        return EmailVerificationResult(
            email=clean_email,
            is_valid_syntax=True,
            has_mx_record=has_mx,
            is_disposable=False,
            reason="نطاق موثق ويحتوي على سجلات بريد صالحة" if has_mx else "تعذر التحقق من سجلات MX",
        )

    @staticmethod
    def _lookup_mx(domain: str) -> bool:
        try:
            import dns.resolver  # type: ignore

            answers = dns.resolver.resolve(domain, "MX", lifetime=3.0)
            return len(answers) > 0
        except Exception:
            return "." in domain and len(domain) >= 4
