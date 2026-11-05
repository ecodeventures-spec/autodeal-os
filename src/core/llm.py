"""Unified AI Model Adapter supporting Google Gemini (Interactions API), OpenAI, Ollama, Claude CLI, and Mock fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Dict, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel

from src.core.config import AppSettings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class UnifiedLLMClient:
    """
    Provides a unified async interface for text and structured JSON generation.
    Primary engine: Google Gemini (`google-genai` >= 2.30.1 using `client.interactions.create`).
    Also supports OpenAI, Ollama, Claude Code CLI (`claude -p`), and intelligent offline fallback.
    """

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.provider = settings.llm.provider.lower()
        self.model = settings.llm.model
        # Enforce non-deprecated Gemini model names
        if self.provider == "gemini" and any(
            legacy in self.model for legacy in ("gemini-1.5", "gemini-2.0", "gemini-2.5")
        ):
            logger.warning(
                "Deprecated Gemini model '%s' requested; substituting 'gemini-3.8-flash'.",
                self.model,
            )
            self.model = "gemini-3.8-flash"

    def _has_live_credentials(self) -> bool:
        if self.provider == "gemini":
            key = self.settings.llm.gemini_api_key
            return bool(key and key != "your_gemini_api_key_here")
        if self.provider == "openai":
            return bool(self.settings.llm.openai_api_key)
        if self.provider in ("ollama", "claude_cli"):
            return True
        return False

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str = "You are an expert B2B AI sales strategist.",
    ) -> str:
        """Generate plain text from the configured LLM provider."""
        if self.provider == "mock" or not self._has_live_credentials():
            return self._fallback_text(prompt, system_instruction)

        try:
            if self.provider == "gemini":
                return await asyncio.to_thread(
                    self._call_gemini_text, prompt, system_instruction
                )
            elif self.provider == "openai":
                return await self._call_openai(prompt, system_instruction)
            elif self.provider == "ollama":
                return await self._call_ollama(prompt, system_instruction)
            elif self.provider == "claude_cli":
                return await asyncio.to_thread(
                    self._call_claude_cli, prompt, system_instruction
                )
        except Exception as exc:
            logger.warning("LLM provider '%s' error (%s); using smart fallback.", self.provider, exc)
        return self._fallback_text(prompt, system_instruction)

    async def generate_structured(
        self,
        prompt: str,
        schema_cls: Type[T],
        system_instruction: str = "You are a precise B2B AI sales agent. Output valid JSON.",
        fallback_factory: Optional[Any] = None,
    ) -> T:
        """Generate structured output validated against a Pydantic model."""
        if self.provider == "mock" or not self._has_live_credentials():
            if fallback_factory:
                return fallback_factory()
            raise RuntimeError("No live credentials and no fallback factory provided.")

        json_schema = schema_cls.model_json_schema()
        try:
            if self.provider == "gemini":
                raw_json = await asyncio.to_thread(
                    self._call_gemini_structured,
                    prompt,
                    system_instruction,
                    json_schema,
                )
                return schema_cls.model_validate_json(raw_json)
            else:
                schema_prompt = (
                    f"{prompt}\n\n"
                    f"Respond ONLY with valid JSON conforming to this schema:\n"
                    f"{json.dumps(json_schema, ensure_ascii=False)}"
                )
                raw_text = await self.generate_text(schema_prompt, system_instruction)
                cleaned = self._extract_json_block(raw_text)
                return schema_cls.model_validate_json(cleaned)
        except Exception as exc:
            logger.warning(
                "Structured generation failed on '%s' (%s); falling back to deterministic generator.",
                self.provider,
                exc,
            )
            if fallback_factory:
                return fallback_factory()
            raise

    # ==========================================
    # Provider Implementations
    # ==========================================
    def _call_gemini_text(self, prompt: str, system_instruction: str) -> str:
        from google import genai

        client = genai.Client(api_key=self.settings.llm.gemini_api_key)
        interaction = client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=prompt,
            generation_config={
                "max_output_tokens": self.settings.llm.max_output_tokens,
            },
        )
        return interaction.output_text or ""

    def _call_gemini_structured(
        self, prompt: str, system_instruction: str, json_schema: Dict[str, Any]
    ) -> str:
        from google import genai

        client = genai.Client(api_key=self.settings.llm.gemini_api_key)
        interaction = client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": json_schema,
            },
            generation_config={
                "max_output_tokens": self.settings.llm.max_output_tokens,
            },
        )
        return interaction.output_text or "{}"

    async def _call_openai(self, prompt: str, system_instruction: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.llm.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model if "gpt" in self.model else "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _call_ollama(self, prompt: str, system_instruction: str) -> str:
        url = f"{self.settings.llm.ollama_base_url.rstrip('/')}/api/generate"
        payload = {
            "model": self.model,
            "system": system_instruction,
            "prompt": prompt,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")

    def _call_claude_cli(self, prompt: str, system_instruction: str) -> str:
        """Harvey-style local subscription execution via Claude Code CLI (`claude -p`)."""
        combined = f"{system_instruction}\n\n{prompt}"
        proc = subprocess.run(
            ["claude", "-p", combined],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        return proc.stdout.strip()

    @staticmethod
    def _extract_json_block(text: str) -> str:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end >= start:
            return text[start : end + 1]
        return text

    @staticmethod
    def _fallback_text(prompt: str, system_instruction: str) -> str:
        return (
            "تم تحليل البيانات بنجاح عبر محرك المحاكاة الذكي (Smart Offline Mode). "
            "للتشغيل المباشر مع Google Gemini، يرجى إضافة GEMINI_API_KEY في ملف .env."
        )
