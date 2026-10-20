"""Tests de la boucle d'outils des fournisseurs, avec des clients factices (aucun appel réseau)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types

from llm_providers.anthropic_provider import AnthropicProvider
from llm_providers.base import LLMError, ToolError, ToolSpec
from llm_providers.gemini_provider import GeminiProvider

SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}


def make_tool(calls: list[dict], fail: bool = False) -> ToolSpec:
    """Outil « read_file » qui enregistre ses arguments et peut échouer sur demande."""

    def handler(args: dict) -> str:
        calls.append(args)
        if fail:
            raise ToolError("fichier introuvable")
        return "contenu"

    return ToolSpec(name="read_file", description="Lit un fichier.", parameters=SCHEMA, handler=handler)


# --- Anthropic ---------------------------------------------------------------------------------------------


class FakeAnthropicClient:
    """Client qui renvoie les réponses prévues et garde une copie des messages envoyés."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = iter(responses)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return next(self._responses)


def tool_use_response() -> Any:
    block = SimpleNamespace(type="tool_use", id="tu_1", name="read_file", input={"path": "a.txt"})
    return SimpleNamespace(stop_reason="tool_use", content=[block])


def text_response(text: str) -> Any:
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def anthropic_provider(responses: list[Any]) -> tuple[AnthropicProvider, FakeAnthropicClient]:
    provider = AnthropicProvider(api_key="x")
    provider._client = client = FakeAnthropicClient(responses)
    return provider, client


def test_anthropic_tool_call_then_answer() -> None:
    calls: list[dict] = []
    provider, client = anthropic_provider([tool_use_response(), text_response("  Verdict  ")])

    assert provider.run_agent("sys", "go", [make_tool(calls)]) == "Verdict"
    assert calls == [{"path": "a.txt"}]
    assert client.requests[0]["tools"][0]["input_schema"] == SCHEMA
    last = client.requests[1]["messages"][-1]
    assert last == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "contenu"}]}


def test_anthropic_tool_error_is_sent_back() -> None:
    provider, client = anthropic_provider([tool_use_response(), text_response("ok")])

    assert provider.run_agent("sys", "go", [make_tool([], fail=True)]) == "ok"
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "introuvable" in result["content"]


def test_anthropic_max_steps() -> None:
    provider, _ = anthropic_provider([tool_use_response() for _ in range(3)])

    with pytest.raises(LLMError, match="max_steps"):
        provider.run_agent("sys", "go", [make_tool([])], max_steps=3)


# --- Gemini ------------------------------------------------------------------------------------------------


class FakeGeminiClient:
    """Client qui renvoie les réponses prévues et garde une copie des contenus envoyés."""

    def __init__(self, responses: list[types.GenerateContentResponse]) -> None:
        self._responses = iter(responses)
        self.requests: list[dict] = []
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.requests.append({**kwargs, "contents": list(kwargs["contents"])})
        return next(self._responses)


def gemini_response(part: types.Part) -> types.GenerateContentResponse:
    content = types.Content(role="model", parts=[part])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def call_response() -> types.GenerateContentResponse:
    call = types.FunctionCall(id="fc_1", name="read_file", args={"path": "a.txt"})
    return gemini_response(types.Part(function_call=call))


def gemini_provider(responses: list[types.GenerateContentResponse]) -> tuple[GeminiProvider, FakeGeminiClient]:
    provider = GeminiProvider(api_key="x")
    provider._client = client = FakeGeminiClient(responses)
    return provider, client


def test_gemini_tool_call_then_answer() -> None:
    calls: list[dict] = []
    provider, client = gemini_provider([call_response(), gemini_response(types.Part.from_text(text=" Verdict "))])

    assert provider.run_agent("sys", "go", [make_tool(calls)]) == "Verdict"
    assert calls == [{"path": "a.txt"}]
    assert client.requests[0]["config"].automatic_function_calling.disable is True
    reply = client.requests[1]["contents"][-1]
    assert reply.role == "user"
    response = reply.parts[0].function_response
    assert (response.id, response.name, response.response) == ("fc_1", "read_file", {"result": "contenu"})


def test_gemini_tool_error_is_sent_back() -> None:
    provider, client = gemini_provider([call_response(), gemini_response(types.Part.from_text(text="ok"))])

    assert provider.run_agent("sys", "go", [make_tool([], fail=True)]) == "ok"
    assert client.requests[1]["contents"][-1].parts[0].function_response.response == {"error": "fichier introuvable"}


def test_gemini_max_steps() -> None:
    provider, _ = gemini_provider([call_response() for _ in range(3)])

    with pytest.raises(LLMError, match="max_steps"):
        provider.run_agent("sys", "go", [make_tool([])], max_steps=3)


def test_exercise_settings_override_env_and_set_temperature() -> None:
    from llm_providers import get_provider
    from llm_providers.gemini_provider import _agent_config

    env = {"ANTHROPIC_API_KEY": "a", "GEMINI_API_KEY": "g", "LLM_PROVIDER": "anthropic", "LLM_MODEL": "autre"}
    provider = get_provider(env, provider="gemini", model="gemini-test", temperature=0.2)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-test"
    assert _agent_config("système", [], provider.temperature).temperature == 0.2


def test_gemini_unknown_model_or_bad_key_raises_config_error(code: int, message: str) -> None:
    from google.genai import errors

    from llm_providers.base import LLMConfigError

    class FailingModels:
        def generate_content(self, **kwargs: Any) -> Any:
            raise errors.ClientError(code, {"error": {"code": code, "message": message, "status": "X"}})

    provider = GeminiProvider(api_key="x")
    provider._client = SimpleNamespace(models=FailingModels())
    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        provider.generate("système", "question")


def _quota_429(quota_id: str, retry_delay: str) -> Any:
    from google.genai import errors

    details = [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay},
    ]
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota", "details": details}})


def test_gemini_daily_quota_stops_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_providers.base import LLMQuotaError

    waits: list[float] = []
    monkeypatch.setattr("llm_providers.gemini_provider.time.sleep", waits.append)

    class DailyQuota:
        def generate_content(self, **kwargs: Any) -> Any:
            raise _quota_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "71541s")

    provider = GeminiProvider(api_key="x")
    provider._client = SimpleNamespace(models=DailyQuota())
    with pytest.raises(LLMQuotaError, match="quota du jour"):
        provider.generate("système", "question")
    assert waits == []  # aucune attente : arrêt immédiat


def test_gemini_minute_quota_waits_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr("llm_providers.gemini_provider.time.sleep", waits.append)

    class MinuteQuotaThenOk:
        calls = 0

        def generate_content(self, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise _quota_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "12s")
            return types.GenerateContentResponse(
                candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text="OK")]))]
            )

    provider = GeminiProvider(api_key="x")
    provider._client = SimpleNamespace(models=MinuteQuotaThenOk())
    assert provider.generate("système", "question") == "OK"
    assert waits == [13.0]  # délai annoncé par Google + 1 s


def _ok_response() -> Any:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text="OK")]))]
    )


def test_gemini_timeout_fails_once_without_silent_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    waits: list[float] = []
    monkeypatch.setattr("llm_providers.gemini_provider.time.sleep", waits.append)

    class SlowModels:
        calls = 0

        def generate_content(self, **kwargs: Any) -> Any:
            self.calls += 1
            raise httpx.ReadTimeout("trop lent")

    provider = GeminiProvider(api_key="x")
    provider._client = SimpleNamespace(models=SlowModels())
    with pytest.raises(LLMError, match="n'a pas répondu"):
        provider.generate("système", "question")
    assert provider._client.models.calls == 1 and waits == []


def test_gemini_server_error_retried_with_visible_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.genai import errors

    waits: list[float] = []
    monkeypatch.setattr("llm_providers.gemini_provider.time.sleep", waits.append)

    class BusyThenOk:
        calls = 0

        def generate_content(self, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise errors.ServerError(
                    503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}
                )
            return _ok_response()

    provider = GeminiProvider(api_key="x")
    provider._client = SimpleNamespace(models=BusyThenOk())
    assert provider.generate("système", "question") == "OK"
    assert waits == [5]


@pytest.mark.parametrize(
    ("error_class", "status", "expected"),
    [
        ("RateLimitError", 429, "LLMQuotaError"),
        ("AuthenticationError", 401, "LLMConfigError"),
        ("PermissionDeniedError", 403, "LLMConfigError"),
        ("NotFoundError", 404, "LLMConfigError"),
    ],
)
def test_anthropic_batch_errors(error_class: str, status: int, expected: str) -> None:
    import anthropic
    import httpx

    from llm_providers import base

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = getattr(anthropic, error_class)("refus", response=httpx.Response(status, request=request), body=None)

    class FailingClient:
        def __init__(self) -> None:
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

        def _create(self, **kwargs: Any) -> Any:
            raise error

    provider = AnthropicProvider(api_key="x")
    provider._client = FailingClient()
    with pytest.raises(getattr(base, expected)):
        provider.generate("système", "question")


def test_gemini_429_without_delay_waits_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from google.genai import errors

    from llm_providers.base import LLMQuotaError
    from llm_providers.gemini_provider import GeminiProvider

    waits: list[float] = []
    monkeypatch.setattr("llm_providers.gemini_provider.time.sleep", waits.append)

    class Saturated:
        calls = 0

        def generate_content(self, **kwargs: object) -> None:
            self.calls += 1
            raise errors.ClientError(429, {"error": {"code": 429, "message": "saturé", "status": "RESOURCE_EXHAUSTED"}})

    provider = GeminiProvider(api_key="x")
    provider._client = SimpleNamespace(models=Saturated())
    with pytest.raises(LLMQuotaError):
        provider.generate("système", "question")
    assert provider._client.models.calls == 4 and waits == [31, 31, 31]
