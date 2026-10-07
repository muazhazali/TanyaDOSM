"""Hosted chat and embedding providers with sanitized failures."""

from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from typing import Any

import httpx
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.exceptions import OutputParserException
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from askdosm.config import Settings
from askdosm.models import TokenUsage


logger = logging.getLogger(__name__)


class HostedProviderError(RuntimeError):
    """A safe provider failure that contains no request or credential data."""


class _UsageCallback(BaseCallbackHandler):
    """Captures token usage from ``on_llm_end`` into a ``TokenUsage`` sink."""

    def __init__(self, usage: TokenUsage):
        self.usage = usage

    def on_llm_end(self, response: Any, **_kwargs: Any) -> None:
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if not token_usage:
            return
        prompt = int(token_usage.get("prompt_tokens", 0) or 0)
        completion = int(token_usage.get("completion_tokens", 0) or 0)
        cached = 0
        details = token_usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens", 0) or 0)
        if prompt or completion:
            self.usage.add(prompt=prompt, completion=completion, cached=cached)


OLLAMA_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4.1-flash": {"input": 0.30, "cached": 0.006, "output": 1.20},
    "deepseek-v4-pro": {"input": 1.32, "cached": 0.044, "output": 3.96},
    "gemma4": {"input": 0.14, "cached": 0.05, "output": 0.40},
    "glm-5.3": {"input": 1.40, "cached": 0.26, "output": 4.40},
    "glm-5.3-flash": {"input": 0.15, "cached": 0.03, "output": 0.50},
}

DEFAULT_PRICING: dict[str, float] = OLLAMA_PRICING["glm-5.3-flash"]


def _pricing_for(model: str) -> dict[str, float]:
    """Resolve the price row for a model name, falling back to glm-5.3-flash."""
    name = (model or "").strip().lower()
    if name in OLLAMA_PRICING:
        return OLLAMA_PRICING[name]
    for key, row in OLLAMA_PRICING.items():
        if name.startswith(key) or key in name:
            return row
    return DEFAULT_PRICING


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

    def collapse_nullable(value: dict[str, Any]) -> None:
        """Replace Pydantic's nullable ``anyOf`` with Groq's type union form."""
        branches = value.get("anyOf")
        if not isinstance(branches, list) or len(branches) != 2:
            return
        null_branches = [branch for branch in branches if branch == {"type": "null"}]
        if len(null_branches) != 1:
            return
        non_null = next(branch for branch in branches if branch != {"type": "null"})
        if "$ref" in non_null:
            prefix = "#/$defs/"
            reference = non_null["$ref"]
            if not isinstance(reference, str) or not reference.startswith(prefix):
                return
            non_null = deepcopy(schema.get("$defs", {}).get(reference.removeprefix(prefix), {}))
        scalar_type = non_null.get("type")
        if not isinstance(scalar_type, str):
            return
        replacement = deepcopy(non_null)
        replacement["type"] = [scalar_type, "null"]
        if "enum" in replacement:
            replacement["enum"] = [*replacement["enum"], None]
        value.clear()
        value.update(replacement)

    def remove_ambiguous_integer_branch(value: dict[str, Any]) -> None:
        """Groq treats integer and number branches in one union as ambiguous."""
        branches = value.get("anyOf")
        if not isinstance(branches, list):
            return
        branch_types = {branch.get("type") for branch in branches if isinstance(branch, dict)}
        if {"integer", "number"}.issubset(branch_types):
            value["anyOf"] = [branch for branch in branches if branch.get("type") != "integer"]

    def normalize(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            value.pop("title", None)
            collapse_nullable(value)
            remove_ambiguous_integer_branch(value)
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
        usage: TokenUsage | None = None,
    ):
        self.runnable = runnable
        self.model = model
        self.max_retries = max_retries
        self.output_schema = output_schema
        self.usage = usage

    def _callbacks(self) -> list:
        if self.usage is None:
            return []
        return [_UsageCallback(self.usage)]

    def invoke(self, messages: Any):
        config = {"callbacks": self._callbacks()} if self._callbacks() else None

        def single(current_messages: Any):
            result = self.runnable.invoke(current_messages, config=config)
            if self.output_schema is not None and not isinstance(result, self.output_schema):
                result = self.output_schema.model_validate(result)
            return result

        return self._run(single, messages)

    def _run(self, single, messages: Any):
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                result = single(messages)
                logger.info(
                    "hosted_provider_request provider=groq model=%s latency_ms=%.2f retry_count=%d status=success",
                    self.model,
                    (time.perf_counter() - started) * 1000,
                    attempt,
                )
                return result
            except Exception as exc:
                status = _status_code(exc)
                transient = _is_transient(exc) or isinstance(exc, OutputParserException)
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


def _extract_json_text(text: str) -> str:
    """Pull a JSON object out of prose or fences when a model ignores json_mode."""
    stripped = text.strip()
    if "```" in stripped:
        for segment in stripped.split("```"):
            candidate = segment.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                stripped = candidate
                break
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        stripped = stripped[start : end + 1]
    return stripped


def _convert_message(message: Any) -> BaseMessage:
    from langchain_core.messages import HumanMessage

    if isinstance(message, BaseMessage):
        return message.model_copy()
    if isinstance(message, tuple) and len(message) == 2:
        role, text = message
        normalized = str(role).lower()
        content = str(text)
        if normalized in {"assistant", "ai"}:
            return AIMessage(content=content)
        if normalized == "system":
            return SystemMessage(content=content)
        if normalized == "tool":
            return ToolMessage(content=content, tool_call_id="legacy")
        return HumanMessage(content=content)
    if isinstance(message, str):
        return HumanMessage(content=message)
    return message


def _json_object_instructions(schema: type[BaseModel]) -> str:
    """Compact field-level guidance for providers that lack json_schema support."""

    def resolve(spec: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(spec, dict):
            return {}
        ref = spec.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            resolved = dict(schema_dict.get("$defs", {}).get(ref.removeprefix("#/$defs/"), {}))
            resolved.update({key: value for key, value in spec.items() if key != "$ref"})
            return resolved
        return spec

    def describe(raw_property_spec: dict[str, Any]) -> tuple[str, bool]:
        spec = resolve(raw_property_spec)
        branches = spec.get("anyOf")
        if isinstance(branches, list) and branches:
            resolved_branches = [resolve(branch) for branch in branches]
            types = [str(branch.get("type")) for branch in resolved_branches if branch.get("type") not in (None, "null")]
            kind = types[0] if types else "object"
            nullable = any(branch.get("type") == "null" for branch in resolved_branches)
            return kind, nullable
        kinds = spec.get("type")
        if isinstance(kinds, list):
            non_null = [kind for kind in kinds if kind != "null"]
            return str(non_null[0] if non_null else "object"), "null" in kinds
        if isinstance(kinds, str):
            return kinds, False
        if spec.get("enum"):
            return "string", False
        return "object", False

    def enum_values(raw_property_spec: dict[str, Any]) -> list | None:
        spec = resolve(raw_property_spec)
        if spec.get("enum"):
            return list(spec["enum"])
        values: list = []
        for branch in spec.get("anyOf") or []:
            branch_spec = resolve(branch)
            values.extend(value for value in (branch_spec.get("enum") or []) if value is not None)
        return values or None

    schema_dict = schema.model_json_schema()
    lines = ["Respond with a single JSON object of type " + schema.__name__ + "."]
    required = set(schema_dict.get("required", []))
    for name, raw_property_spec in schema_dict.get("properties", {}).items():
        spec = resolve(raw_property_spec)
        kind, nullable = describe(raw_property_spec)
        marker = "required" if name in required else "optional"
        line = f'- "{name}" ({marker}; {kind}{" or null" if nullable else ""}'
        enum = enum_values(raw_property_spec)
        if enum:
            line += "; must be one of " + json.dumps(enum, default=str)
        line += ")"
        description = spec.get("description")
        if description:
            line += f": {description}"
        lines.append(line)
    for nested, nested_spec in (schema_dict.get("$defs") or {}).items():
        nested_props = (nested_spec or {}).get("properties", {})
        if nested_props:
            lines.append(f'- "{nested}" values have fields: ' + ", ".join(f'"{key}"' for key in nested_props))
            for key, raw_prop_spec in nested_props.items():
                prop_spec = resolve(raw_prop_spec)
                enum = enum_values(raw_prop_spec)
                kind, nullable = describe(raw_prop_spec)
                line = f'  - "{key}" ({kind}{" or null" if nullable else ""}'
                if enum:
                    line += "; must be one of " + json.dumps(enum, default=str)
                line += ")"
                lines.append(line)
    lines.append("Use null only for fields marked optional with 'or null'. Never invent new field names.")
    lines.append("Return only the JSON object with no markdown, comments, or extra text.")
    return "\n".join(lines)


class _StructuredJsonInvoker(_StructuredInvoker):
    """json_mode wrapper: injects schema guidance, parses and validates raw JSON output."""

    def __init__(
        self,
        runnable: Any,
        model: str,
        max_retries: int,
        output_schema: type[BaseModel],
        instructions: str,
        usage: TokenUsage | None = None,
    ):
        super().__init__(runnable, model, max_retries, output_schema, usage)
        self.instructions = instructions

    def invoke(self, messages: Any):
        prepared = self._prepare(messages)
        config = {"callbacks": self._callbacks()} if self._callbacks() else None

        def single(prepared_messages: list):
            raw = self.runnable.invoke(prepared_messages, config=config)
            if isinstance(raw, self.output_schema):
                return raw
            if isinstance(raw, BaseModel):
                return self.output_schema.model_validate(raw.model_dump())
            text = raw.content if isinstance(raw, AIMessage) else str(raw)
            if not isinstance(text, str):
                text = "".join(part for part in text if isinstance(part, str))
            parsed_raw = json.loads(_extract_json_text(text))
            # Some models envelope the payload under the schema/class name.
            if isinstance(parsed_raw, dict) and len(parsed_raw) == 1:
                inner_key = next(iter(parsed_raw))
                inner = parsed_raw[inner_key]
                if isinstance(inner, dict) and inner:
                    parsed_raw = inner
            try:
                return self.output_schema.model_validate(parsed_raw)
            except ValidationError as exc:
                raise OutputParserException(f"Model JSON did not match {self.output_schema.__name__}.") from exc

        return self._run(single, prepared)

    def _prepare(self, messages: Any) -> list:
        prepared: list = []
        injected = False
        for message in list(messages):
            converted = _convert_message(message)
            if (
                not injected
                and isinstance(converted.content, str)
                and converted.content.strip()
                and not isinstance(converted, ToolMessage)
                and not isinstance(converted, SystemMessage)
            ):
                converted.content = f"{converted.content}\n\n{self.instructions}"
                injected = True
            prepared.append(converted)
        if not injected:
            prepared.insert(0, SystemMessage(content=self.instructions))
        return prepared


class GroqChatModel:
    """LangChain-compatible Groq model enforcing strict JSON Schema output."""

    def __init__(self, settings: Settings):
        settings.require_groq_credentials()
        self.model = settings.chat_model
        self.max_retries = settings.provider_max_retries
        self.json_object_mode = "ollama.com" in settings.groq_base_url.lower()
        pricing = _pricing_for(settings.chat_model)
        self.usage = TokenUsage(
            model=settings.chat_model,
            input_price_per_m=pricing["input"],
            cached_input_price_per_m=pricing["cached"],
            output_price_per_m=pricing["output"],
        )
        self._model = ChatOpenAI(
            model=settings.chat_model,
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            temperature=0,
            timeout=settings.request_timeout,
            max_retries=0,
            reasoning_effort="low",
            max_tokens=4000,
        )

    def with_structured_output(self, schema: type):
        if self.json_object_mode:
            # Ollama Cloud's OpenAI endpoint accepts json_schema but silently
            # ignores it; json_object mode is the only enforced variant.
            instructions = _json_object_instructions(schema)
            runnable = self._model.with_structured_output(schema, method="json_mode")
            return _StructuredJsonInvoker(runnable, self.model, self.max_retries, schema, instructions, usage=self.usage)
        strict_schema = _strict_json_schema(schema)
        runnable = self._model.with_structured_output(strict_schema, method="json_schema", strict=True)
        return _StructuredInvoker(runnable, self.model, self.max_retries, schema, usage=self.usage)


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
