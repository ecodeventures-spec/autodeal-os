"""Connection Diagnostics Service: Tests AI, SMTP, and IMAP connections from the Settings Control Center."""

from __future__ import annotations

import asyncio
import imaplib
import smtplib
import time
from typing import Any, Dict

from src.core.config import AppSettings
from src.core.llm import UnifiedLLMClient


async def test_ai_engine_connection(settings: AppSettings) -> Dict[str, Any]:
    """Test AI provider connectivity and latency."""
    start = time.perf_counter()
    client = UnifiedLLMClient(settings)
    has_creds = client._has_live_credentials()
    try:
        reply = await client.generate_text(
            prompt="أجب بكلمة واحدة فقط: جاهز",
            system_instruction="أنت مساعد اختبار اتصال سريع.",
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "success",
            "live_connection": has_creds,
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "latency_ms": elapsed_ms,
            "sample_output": reply[:80],
            "message": (
                f"تم الاتصال بنجاح بمحرك ({settings.llm.provider.upper()} - {settings.llm.model}) خلال {elapsed_ms} مللي ثانية."
                if has_creds
                else f"يعمل النظام حالياً في وضع المحاكاة الذكي الفوري ({elapsed_ms}ms). أدخل مفتاح API للاتصال السحابي المباشر."
            ),
        }
    except Exception as exc:
        return {
            "status": "error",
            "live_connection": False,
            "provider": settings.llm.provider,
            "message": f"تعذر الاتصال بمزود الذكاء الاصطناعي: {exc}",
        }


def _smtp_check_sync(host: str, port: int, username: str, password: str) -> Dict[str, Any]:
    start = time.perf_counter()
    if not username or not password:
        return {
            "status": "simulated",
            "live_connection": False,
            "message": "لم يتم إدخال اسم مستخدم أو كلمة مرور SMTP بعد. يعمل النظام بأمان في وضع المحاكاة (Dry-Run).",
        }
    try:
        with smtplib.SMTP(host, port, timeout=8) as server:
            server.ehlo()
            if port in (587, 2525):
                server.starttls()
                server.ehlo()
            server.login(username, password)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "success",
            "live_connection": True,
            "latency_ms": elapsed_ms,
            "message": f"تم الاتصال والمصادقة بنجاح مع خادم البريد الصادر ({host}:{port}) خلال {elapsed_ms}ms.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "live_connection": False,
            "message": f"فشل الاتصال بخادم SMTP ({host}:{port}): {exc}",
        }


def _imap_check_sync(host: str, port: int, username: str, password: str) -> Dict[str, Any]:
    start = time.perf_counter()
    if not username or not password:
        return {
            "status": "simulated",
            "live_connection": False,
            "message": "لم يتم إدخال بيانات حساب IMAP بعد. يمكنك استخدام صندوق محاكاة الردود التفاعلي في لوحة التحكم.",
        }
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(username, password)
        mail.select("INBOX")
        mail.logout()
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "success",
            "live_connection": True,
            "latency_ms": elapsed_ms,
            "message": f"تم الاتصال بنجاح بصندوق الوارد IMAP ({host}:{port}) خلال {elapsed_ms}ms.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "live_connection": False,
            "message": f"فشل الاتصال بخادم IMAP ({host}:{port}): {exc}",
        }


async def test_email_connections(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    imap_host: str,
    imap_port: int,
    imap_username: str,
    imap_password: str,
) -> Dict[str, Any]:
    smtp_res = _smtp_check_sync( smtp_host, smtp_port, smtp_username, smtp_password
    )
    imap_res = _imap_check_sync( imap_host, imap_port, imap_username, imap_password
    )
    return {
        "smtp": smtp_res,
        "imap": imap_res,
    }
