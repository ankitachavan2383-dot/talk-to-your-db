"""Thin xAI/Grok client using the OpenAI-compatible SDK (API client only - no agent framework)."""
from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def chat(self, system: str, user: str, history: list[dict] | None = None) -> str: ...
    def structured(self, system: str, user: str, schema: type[T], history: list[dict] | None = None) -> T: ...


def extract_json(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model output")
    return raw[start : end + 1]


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.groq_model
        self._temp = settings.llm_temperature
        self._client = OpenAI(
            api_key=settings.groq_api_key or "missing",
            base_url=settings.groq_base_url,
            timeout=settings.llm_timeout_s,
            max_retries=3,  # SDK backs off automatically on Groq 429 rate limits
        )

    def _complete(self, system: str, user: str, history: list[dict] | None, json_mode: bool) -> str:
        messages = [{"role": "system", "content": system}]
        for m in (history or [])[-6:]:
            messages.append({"role": m["role"], "content": str(m["content"])[:600]})
        messages.append({"role": "user", "content": user})
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            resp = self._client.chat.completions.create(
                model=self._model, messages=messages, temperature=self._temp, **kwargs
            )
        except Exception as exc:  # network / auth / rate limit
            raise LLMError(f"LLM request failed: {exc.__class__.__name__}") from exc
        return resp.choices[0].message.content or ""

    def chat(self, system: str, user: str, history: list[dict] | None = None) -> str:
        return self._complete(system, user, history, json_mode=False)

    def structured(self, system: str, user: str, schema: type[T], history: list[dict] | None = None) -> T:
        sys_prompt = (
            f"{system}\n\nReply with ONLY a JSON object (an instance of the schema, NOT the schema itself) "
            f"that conforms to this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        prompt, last_err = user, None
        for _ in range(2):
            try:
                raw = self._complete(sys_prompt, prompt, history, json_mode=True)
                return schema.model_validate_json(extract_json(raw))
            except (ValidationError, ValueError, LLMError) as exc:  # LLMError: Groq 400 json_validate_failed
                last_err = exc
                prompt = f"{user}\n\nYour previous reply was invalid ({str(exc)[:300]}). Return corrected JSON only."
        raise LLMError(f"model did not return valid {schema.__name__}: {last_err}")