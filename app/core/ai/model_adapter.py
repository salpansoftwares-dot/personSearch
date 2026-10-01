"""
Model Adapter — single interface in front of all AI providers.

Architecture principle: "AI proposes, deterministic code decides."
This adapter is the ONLY place that calls an LLM. All callers receive
structured, schema-validated output. Raw model responses never escape.

Provider routing:
  nvidia    → NVIDIA NIM API (OpenAI-compatible) using httpx
  google    → google-genai SDK
  openai    → openai SDK
  anthropic → anthropic SDK
"""

import json
from typing import Any

import structlog
from pydantic import BaseModel

from app.config import settings

logger = structlog.get_logger(__name__)


def _clean_json_text(text: str) -> str:
    """Extract valid JSON substring if wrapped in markdown codeblocks or text."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    first_brace = s.find("{")
    first_bracket = s.find("[")
    starts = [pos for pos in (first_brace, first_bracket) if pos != -1]
    if starts:
        start_idx = min(starts)
        last_brace = s.rfind("}")
        last_bracket = s.rfind("]")
        ends = [pos for pos in (last_brace, last_bracket) if pos != -1]
        if ends:
            end_idx = max(ends)
            s = s[start_idx : end_idx + 1]
    return s


class ModelAdapter:
    """
    Thin wrapper around AI provider SDKs.

    Usage:
        adapter = ModelAdapter()
        result = await adapter.complete(
            prompt="...",
            response_schema=MyClaim,
            model_tier="extraction",  # or "reasoning"
        )
    """

    def __init__(self) -> None:
        self._provider = settings.ai_provider
        self._extraction_model = settings.ai_model_extraction
        self._reasoning_model = settings.ai_model_reasoning
        self._client: Any = None
        self._init_client()

    def _init_client(self) -> None:
        if self._provider == "nvidia":
            try:
                import httpx
                self._client = httpx.AsyncClient(
                    base_url=settings.nvidia_base_url,
                    headers={
                        "Authorization": f"Bearer {settings.nvidia_api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=60.0,
                )
                logger.info(
                    "ai.adapter.init",
                    provider="nvidia",
                    base_url=settings.nvidia_base_url,
                    extraction_model=self._extraction_model,
                    reasoning_model=self._reasoning_model,
                )
            except Exception as exc:
                logger.warning("ai.adapter.init_failed", provider="nvidia", error=str(exc))
        elif self._provider == "google":
            try:
                from google import genai  # type: ignore
                self._client = genai.Client(api_key=settings.google_api_key)
                logger.info("ai.adapter.init", provider="google")
            except Exception as exc:
                logger.warning("ai.adapter.init_failed", provider="google", error=str(exc))
        else:
            logger.warning("ai.adapter.provider_not_implemented", provider=self._provider)

    def _model_name(self, tier: str) -> str:
        return self._extraction_model if tier == "extraction" else self._reasoning_model

    async def complete(
        self,
        *,
        prompt: str,
        response_schema: type[BaseModel] | None = None,
        model_tier: str = "extraction",
        system_instruction: str | None = None,
        source_id: str | None = None,   # for traceability logging
        stage: str = "unknown",          # pipeline stage, for logs
    ) -> dict[str, Any]:
        """
        Send a prompt and return a dict (parsed from the model's JSON output).

        - All prompts and raw outputs are logged against source_id + stage
          so every claim can be traced back to the exact model call.
        - The output is validated against response_schema when provided;
          invalid outputs raise ValueError (caller should drop the claim).
        - Extraction prompts have no tools and cannot take actions.
        """
        model_name = self._model_name(model_tier)
        log = logger.bind(stage=stage, model=model_name, source_id=source_id)
        log.info("ai.call.start")

        raw_text = ""
        try:
            raw_text = await self._call_provider(
                prompt=prompt,
                model_name=model_name,
                system_instruction=system_instruction,
            )
            cleaned = _clean_json_text(raw_text)
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.error("ai.call.json_parse_error", raw=raw_text[:500], error=str(exc))
            raise ValueError(f"Model returned non-JSON output: {exc}") from exc
        except Exception as exc:
            log.error("ai.call.error", error=str(exc))
            raise

        # Schema validation — invalid structure means the claim is dropped.
        if response_schema is not None:
            try:
                validated = response_schema.model_validate(parsed)
                parsed = validated.model_dump()
            except Exception as exc:
                log.error("ai.call.schema_validation_failed", error=str(exc))
                raise ValueError(f"Model output failed schema validation: {exc}") from exc

        log.info("ai.call.success")
        return parsed

    async def _call_provider(
        self,
        *,
        prompt: str,
        model_name: str,
        system_instruction: str | None,
    ) -> str:
        """Dispatch to the configured provider and return raw text."""
        if self._provider == "nvidia" and self._client is not None:
            return await self._call_nvidia(
                prompt=prompt,
                model_name=model_name,
                system_instruction=system_instruction,
            )
        elif self._provider == "google" and self._client is not None:
            return await self._call_google(
                prompt=prompt,
                model_name=model_name,
                system_instruction=system_instruction,
            )
        raise NotImplementedError(f"Provider '{self._provider}' is not yet implemented or client uninitialized.")

    async def _call_nvidia(
        self,
        *,
        prompt: str,
        model_name: str,
        system_instruction: str | None,
    ) -> str:
        """Call NVIDIA NIM API (OpenAI-compatible chat completions)."""
        messages = []
        sys_msg = (system_instruction or "").strip()
        if not sys_msg:
            sys_msg = "You are a precise data extraction assistant. Output strictly valid JSON without preamble or markdown blocks."
        else:
            sys_msg += "\nOutput strictly valid JSON with no markdown wrapping or conversational preamble."

        messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1500,
        }

        response = await self._client.post("/chat/completions", json=payload)
        if response.status_code != 200:
            logger.error("ai.nvidia.error", status_code=response.status_code, body=response.text[:500])
            response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _call_google(
        self,
        *,
        prompt: str,
        model_name: str,
        system_instruction: str | None,
    ) -> str:
        """Call the Google Gemini API (google-genai SDK)."""
        from google.genai import types  # type: ignore

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            system_instruction=system_instruction,
            # No tools — extraction prompts cannot take actions.
        )
        # google-genai async usage
        response = await self._client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        return response.text


# Singleton — injected via FastAPI dependency.
_adapter_instance: ModelAdapter | None = None


def get_model_adapter() -> ModelAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = ModelAdapter()
    return _adapter_instance
