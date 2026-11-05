"""Async SMTP Sender and IMAP Inbox Poller with Dry-Run protection."""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import smtplib
from email.header import decode_header
from email.message import EmailMessage
from typing import Dict, List

from src.core.config import AppSettings

logger = logging.getLogger(__name__)


class MailerService:
    """Handles outbound SMTP delivery and inbound IMAP polling."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.sender_cfg = settings.sender

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
    ) -> bool:
        """Send an email via SMTP, or simulate delivery when in Dry-Run mode."""
        if self.settings.system.dry_run or not self.sender_cfg.smtp_password:
            logger.info("[DRY-RUN] Simulated sending email to %s | Subject: %s", to_email, subject)
            return True

        msg = EmailMessage()
        msg["From"] = f"{self.sender_cfg.sender_name} <{self.sender_cfg.sender_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            return await asyncio.to_thread(self._send_smtp_sync, msg)
        except Exception as exc:
            logger.error("Failed to send SMTP email to %s: %s", to_email, exc)
            return False

    def _send_smtp_sync(self, msg: EmailMessage) -> bool:
        with smtplib.SMTP(self.sender_cfg.smtp_host, self.sender_cfg.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(self.sender_cfg.smtp_username, self.sender_cfg.smtp_password)
            server.send_message(msg)
        return True

    async def poll_unseen_replies(self) -> List[Dict[str, str]]:
        """Fetch unread emails from IMAP inbox."""
        if (
            self.settings.system.dry_run
            or not self.sender_cfg.imap_username
            or not self.sender_cfg.imap_password
        ):
            return []

        return await asyncio.to_thread(self._fetch_imap_sync)

    def _fetch_imap_sync(self) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        try:
            mail = imaplib.IMAP4_SSL(self.sender_cfg.imap_host, self.sender_cfg.imap_port)
            mail.login(self.sender_cfg.imap_username, self.sender_cfg.imap_password)
            mail.select("INBOX")
            status, response = mail.search(None, "(UNSEEN)")
            if status != "OK" or not response or not response[0]:
                mail.logout()
                return []

            for num in response[0].split():
                _, data = mail.fetch(num, "(RFC822)")
                for response_part in data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        from_raw = msg.get("From", "")
                        from_addr = email.utils.parseaddr(from_raw)[1]
                        subject = self._decode_mime_words(msg.get("Subject", ""))
                        body_text = self._extract_text_payload(msg)
                        messages.append(
                            {
                                "from_email": from_addr,
                                "subject": subject,
                                "body": body_text,
                            }
                        )
            mail.logout()
        except Exception as exc:
            logger.warning("IMAP polling error: %s", exc)
        return messages

    @staticmethod
    def _decode_mime_words(header_val: str) -> str:
        decoded_parts = decode_header(header_val)
        fragments: List[str] = []
        for content, charset in decoded_parts:
            if isinstance(content, bytes):
                fragments.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                fragments.append(str(content))
        return "".join(fragments)

    @staticmethod
    def _extract_text_payload(msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disp = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(msg.get_content_charset() or "utf-8", errors="replace").strip()
        return ""
