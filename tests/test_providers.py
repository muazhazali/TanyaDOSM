from pathlib import Path

import httpx
import pytest

import askdosm.providers as providers
from askdosm.catalogue import Catalogue
from askdosm.config import Settings
from askdosm.models import QueryPlan, QuestionIntent


def provider_settings(**updates) -> Settings:
    values = {
        "chat_model": "openai/gpt-oss-20b",
        "groq_api_key": "groq-test-key",
        "groq_base_url": "https://api.groq.com/openai/v1",
        "embedding_model": "@cf/baai/bge-m3",
        "cloudflare_account_id": "account-id",
        "cloudflare_api_token": "cloudflare-test-token",
        "cloudflare_base_url": "https://api.cloudflare.com/client/v4/accounts",
    }
    values.update(updates)
    return Settings(**values)


def test_groq_uses_strict_json_schema(monkeypatch):
    observed = {}

    class FakeRunnable:
        def invoke(self, messages):
            return QuestionIntent(metric="population")

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            observed["init"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            observed["schema"] = schema
            observed["structured"] = kwargs
            return FakeRunnable()

    monkeypatch.setattr(providers, "ChatOpenAI", FakeChatOpenAI)
    model = providers.GroqChatModel(provider_settings())
    result = model.with_structured_output(QuestionIntent).invoke([("human", "population")])

    assert result.metric == "population"
    assert observed["init"]["base_url"] == "https://api.groq.com/openai/v1"
    assert observed["init"]["max_retries"] == 0
    assert observed["init"]["reasoning_effort"] == "low"
    assert observed["schema"]["name"] == "QuestionIntent"
    assert observed["schema"]["strict"] is True
    assert set(observed["schema"]["schema"]["required"]) == set(
        observed["schema"]["schema"]["properties"]
    )
    assert "default" not in str(observed["schema"]["schema"])
    assert observed["structured"] == {"method": "json_schema", "strict": True}


def test_groq_schema_collapses_nullable_enum_references():
    schema = providers._strict_json_schema(QuestionIntent)["schema"]

    assert schema["properties"]["requested_output"] == {
        "enum": ["none", "line", "bar", "ranking_bar", "table", None],
        "type": ["string", "null"],
    }
    assert schema["properties"]["domain"] == {"type": ["string", "null"]}


def test_groq_schema_removes_ambiguous_integer_number_union():
    schema = providers._strict_json_schema(QueryPlan)["schema"]
    value_schema = schema["$defs"]["FilterSpec"]["properties"]["value"]

    def assert_no_integer_number_union(value):
        if isinstance(value, dict):
            branches = value.get("anyOf", [])
            types = {branch.get("type") for branch in branches if isinstance(branch, dict)}
            assert not {"integer", "number"}.issubset(types)
            for nested in value.values():
                assert_no_integer_number_union(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_no_integer_number_union(nested)

    assert_no_integer_number_union(value_schema)


def test_groq_retries_transient_failures_without_exposing_details(monkeypatch):
    calls = 0

    class FakeRunnable:
        def invoke(self, messages):
            nonlocal calls
            calls += 1
            if calls < 3:
                request = httpx.Request("POST", "https://api.groq.com")
                response = httpx.Response(429, request=request, headers={"retry-after": "0"})
                raise httpx.HTTPStatusError("secret response", request=request, response=response)
            return QuestionIntent(metric="population")

    monkeypatch.setattr(providers.time, "sleep", lambda _: None)
    result = providers._StructuredInvoker(FakeRunnable(), "model", 2).invoke([])

    assert result.metric == "population"
    assert calls == 3


def test_groq_authentication_error_is_sanitized():
    class FakeRunnable:
        def invoke(self, messages):
            request = httpx.Request("POST", "https://api.groq.com")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("contains-sensitive-provider-body", request=request, response=response)

    with pytest.raises(providers.HostedProviderError, match="authentication failed") as caught:
        providers._StructuredInvoker(FakeRunnable(), "model", 2).invoke([])

    assert "sensitive" not in str(caught.value)


def test_cloudflare_batches_and_validates_vectors():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer cloudflare-test-token"
        assert request.url.path.endswith("/account-id/ai/run/@cf/baai/bge-m3")
        return httpx.Response(200, json={"result": {"data": [[1, 0], [0, 1]], "shape": [2, 2]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    embedder = providers.CloudflareEmbeddings(provider_settings(), client=client)

    assert embedder.embed_documents(["one", "two"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_cloudflare_failure_falls_back_to_lexical_search(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request)

    embedder = providers.CloudflareEmbeddings(
        provider_settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    intent = QuestionIntent(domain="demography", metric="population", geography_level="state", latest=True)

    results = Catalogue(Path("data/catalogue.json")).search_hybrid(
        "negeri paling sedikit penduduk?", intent, embedder, tmp_path
    )

    assert results[0].dataset_id == "population_state"


def test_cloudflare_rejects_inconsistent_dimensions():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"data": [[1, 0], [1]]}})

    embedder = providers.CloudflareEmbeddings(
        provider_settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(providers.HostedProviderError, match="temporarily unavailable"):
        embedder.embed_documents(["one", "two"])


def test_missing_groq_key_is_rejected():
    with pytest.raises(RuntimeError, match="ASKDOSM_GROQ_API_KEY"):
        Settings(groq_api_key="").require_groq_credentials()
