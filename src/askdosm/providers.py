"""Hosted chat and embedding providers with sanitized failures."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from askdosm.config import Settings


logger = logging.getLogger(__name__)


class HostedProviderError(RuntimeError):
    """A safe provider failure that contains no request or credential data."""


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    return status if isinstance(status, int) else getattr(response, "status_code", None)


def _is_transient(exc: Exception) -> bool:
    status = _status_code(exc)
    sdk_transient = type(exc).__name__ in {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError"}
    return sdk_transient or isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)) or status == 429 or (
        isinstance(status, int) and status >= 500
    )


def _strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert Pydantic output into Groq's strict JSON Schema subset."""
    schema = model.model_json_schema()

    def normalize(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            value.pop("title", None)
            properties = value.get("properties")
            if isinstance(properties, dict):
                value["required"] = list(properties)
                value["additionalProperties"] = False
            for nested in value.values():
                normalize(nested)
        elif isinstance(value, list):
            for nested in value:
                normalize(nested)

    normalize(schema)
    return {"name": model.__name__, "strict": True, "schema": schema}


class _StructuredInvoker:
    def __init__(
        self,
        runnable: Any,
        model: str,
        max_retries: int,
        output_schema: type[BaseModel] | None = None,
    ):
        self.runnable = runnable
        self.model = model
        self.max_retries = max_retries
        self.output_schema = output_schema

    def invoke(self, messages: Any):
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                result = self.runnable.invoke(messages)
                if self.output_schema is not None and not isinstance(result, self.output_schema):
                    result = self.output_schema.model_validate(result)
                logger.info(
                    "hosted_provider_request provider=groq model=%s latency_ms=%.2f retry_count=%d status=success",
                    self.model,
                    (time.perf_counter() - started) * 1000,
                    attempt,
                )
                return result
            except Exception as exc:
                status = _status_code(exc)
                transient = _is_transient(exc)
                logger.warning(
                    "hosted_provider_request provider=groq model=%s latency_ms=%.2f retry_count=%d status=failed http_status=%s transient=%s",
                    self.model,
                    (time.perf_counter() - started) * 1000,
                    attempt,
                    status or "none",
                    transient,
                )
                if transient and attempt < self.max_retries:
                    retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
                    try:
                        delay = min(float(retry_after), 8.0) if retry_after else min(2**attempt, 8)
                    except (TypeError, ValueError):
                        delay = min(2**attempt, 8)
                    time.sleep(delay)
                    continue
                if status in {401, 403}:
                    raise HostedProviderError("Hosted language model authentication failed.") from None
                if status == 429:
                    raise HostedProviderError("Hosted language model free-tier quota is temporarily unavailable.") from None
                raise HostedProviderError("Hosted language model is temporarily unavailable.") from None
        raise HostedProviderError("Hosted language model is temporarily unavailable.")


class GroqChatModel:
    """LangChain-compatible Groq model enforcing strict JSON Schema output."""

    def __init__(self, settings: Settings):
        settings.require_groq_credentials()
        self.model = settings.chat_model
        self.max_retries = settings.provider_max_retries
        self._model = ChatOpenAI(
            model=settings.chat_model,
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            temperature=0,
            timeout=settings.request_timeout,
            max_retries=0,
            reasoning_effort="low",
        )

    def with_structured_output(self, schema: type):
        strict_schema = _strict_json_schema(schema)
        runnable = self._model.with_structured_output(strict_schema, method="json_schema", strict=True)
        return _StructuredInvoker(runnable, self.model, self.max_retries, schema)


class CloudflareEmbeddings:
    """Cloudflare Workers AI embedding adapter using the native REST response."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None):
        self.model = settings.embedding_model
        self.account_id = settings.cloudflare_account_id.strip()
        self.api_token = settings.cloudflare_api_token.strip()
        self.base_url = settings.cloudflare_base_url.rstrip("/")
        self.timeout = settings.request_timeout
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.account_id and self.api_token)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.configured:
            raise HostedProviderError("Hosted embeddings are not configured.")
        url = f"{self.base_url}/{self.account_id}/ai/run/{self.model}"
        started = time.perf_counter()
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_token}"},
                json={"text": texts},
            )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result", payload)
            vectors = result.get("data")
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise ValueError("unexpected vector count")
            normalized = [[float(value) for value in vector] for vector in vectors]
            dimensions = {len(vector) for vector in normalized}
            if len(dimensions) != 1 or not next(iter(dimensions), 0):
                raise ValueError("inconsistent embedding dimensions")
            logger.info(
                "hosted_provider_request provider=cloudflare model=%s latency_ms=%.2f inputs=%d status=success",
                self.model,
                (time.perf_counter() - started) * 1000,
                len(texts),
            )
            return normalized
        except Exception as exc:
            logger.warning(
                "hosted_provider_request provider=cloudflare model=%s latency_ms=%.2f inputs=%d status=failed http_status=%s",
                self.model,
                (time.perf_counter() - started) * 1000,
                len(texts),
                _status_code(exc) or "none",
            )
            raise HostedProviderError("Hosted embeddings are temporarily unavailable.") from None
        finally:
            if self._client is None and "client" in locals():
                client.close()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


def create_chat_model(settings: Settings) -> GroqChatModel:
    return GroqChatModel(settings)


def create_embedder(settings: Settings) -> CloudflareEmbeddings:
    return CloudflareEmbeddings(settings)


def check_groq(settings: Settings) -> str:
    if not settings.groq_api_key.strip():
        return "unavailable"
    try:
        response = httpx.get(
            f"{settings.groq_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=2,
        )
        if not response.is_success:
            return "unavailable"
        models = response.json().get("data", [])
        return "ready" if any(item.get("id") == settings.chat_model for item in models) else "unavailable"
    except Exception:
        return "unavailable"


def check_cloudflare(settings: Settings) -> str:
    if not settings.cloudflare_account_id.strip() or not settings.cloudflare_api_token.strip():
        return "unavailable"
    try:
        response = httpx.get(
            f"{settings.cloudflare_base_url.rstrip('/')}/{settings.cloudflare_account_id}/ai/models/search",
            headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
            params={"search": settings.embedding_model},
            timeout=2,
        )
        return "ready" if response.is_success else "unavailable"
    except Exception:
        return "unavailable"
