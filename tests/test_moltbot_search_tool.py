"""Tests for the web_search tool loop and the legacy SEARCH: safety net."""
import sys, os, importlib.util, types, json, asyncio

_src = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, _src)
for _mod in ('psycopg', 'psycopg_pool', 'google.generativeai'):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

_spec = importlib.util.spec_from_file_location(
    "handlers.moltbot_handlers",
    os.path.join(_src, "handlers", "moltbot_handlers.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["handlers.moltbot_handlers"] = _mod
_spec.loader.exec_module(_mod)
MoltbotHandlers = _mod.MoltbotHandlers
_AIConnectionError = _mod._AIConnectionError

import pytest
from unittest.mock import AsyncMock, MagicMock


def _handler():
    h = MoltbotHandlers.__new__(MoltbotHandlers)
    h._brave_search = AsyncMock(return_value="- Курс: 41.5 грн")
    return h


def _tool_call(query, cid="call_1"):
    return {"id": cid, "type": "function",
            "function": {"name": "web_search", "arguments": json.dumps({"query": query})}}


def _resp(content=None, tool_calls=None):
    msg = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


class TestCompleteWithTools:
    @pytest.mark.asyncio
    async def test_plain_answer_passes_through(self):
        h = _handler()
        post = AsyncMock(return_value=_resp("привет"))
        out = await h._complete_with_tools(post, {"model": "m", "messages": [{"role": "user", "content": "хай"}]}, 10)
        assert out == "привет"
        assert post.await_count == 1
        req = post.await_args.args[0]
        assert req["tools"][0]["function"]["name"] == "web_search"
        assert req["tool_choice"] == "auto"
        h._brave_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tool_call_then_answer(self):
        h = _handler()
        post = AsyncMock(side_effect=[
            _resp(None, [_tool_call("курс доллара")]),
            _resp("41.5 грн, bro"),
        ])
        out = await h._complete_with_tools(post, {"model": "m", "messages": [{"role": "user", "content": "курс?"}]}, 10)
        assert out == "41.5 грн, bro"
        h._brave_search.assert_awaited_once_with("курс доллара")
        second = post.await_args_list[1].args[0]
        roles = [m["role"] for m in second["messages"]]
        assert roles == ["user", "assistant", "tool"]
        assert second["messages"][1]["tool_calls"][0]["id"] == "call_1"
        assert second["messages"][2]["tool_call_id"] == "call_1"
        assert "41.5" in second["messages"][2]["content"]

    @pytest.mark.asyncio
    async def test_tool_rounds_are_capped(self):
        h = _handler()
        post = AsyncMock(side_effect=[
            _resp(None, [_tool_call("a", "c1")]),
            _resp(None, [_tool_call("b", "c2")]),
            _resp("финальный ответ", [_tool_call("c", "c3")]),  # ignored: tools were disabled
        ])
        out = await h._complete_with_tools(post, {"model": "m", "messages": [{"role": "user", "content": "x"}]}, 10)
        assert out == "финальный ответ"
        assert post.await_count == 3
        assert post.await_args_list[2].args[0]["tool_choice"] == "none"
        assert h._brave_search.await_count == 2

    @pytest.mark.asyncio
    async def test_no_results_tells_model_honestly(self):
        h = _handler()
        h._brave_search = AsyncMock(return_value="")
        post = AsyncMock(side_effect=[_resp(None, [_tool_call("ерунда")]), _resp("не нашёл")])
        out = await h._complete_with_tools(post, {"model": "m", "messages": []}, 10)
        assert out == "не нашёл"
        tool_msg = post.await_args_list[1].args[0]["messages"][-1]
        assert "ничего не нашлось" in tool_msg["content"]

    @pytest.mark.asyncio
    async def test_provider_without_tools_retries_without_them(self):
        h = _handler()
        post = AsyncMock(side_effect=[
            _AIConnectionError("Together.ai 400: tools not supported for this model"),
            _resp("ок без тулов"),
        ])
        out = await h._complete_with_tools(post, {"model": "m", "messages": []}, 10)
        assert out == "ок без тулов"
        assert "tools" not in post.await_args_list[1].args[0]

    @pytest.mark.asyncio
    async def test_other_errors_propagate(self):
        h = _handler()
        post = AsyncMock(side_effect=_AIConnectionError("OpenRouter 500"))
        with pytest.raises(_AIConnectionError):
            await h._complete_with_tools(post, {"model": "m", "messages": []}, 10)

    @pytest.mark.asyncio
    async def test_unknown_tool_and_bad_args(self):
        h = _handler()
        assert "нет" in await h._execute_tool_call({"function": {"name": "nope", "arguments": "{}"}})
        assert "пустой" in await h._execute_tool_call({"function": {"name": "web_search", "arguments": "{}"}})
        # malformed JSON → treat raw string as query
        out = await h._execute_tool_call({"function": {"name": "web_search", "arguments": "курс"}})
        h._brave_search.assert_awaited_with("курс")
        assert "Результаты поиска" in out


class TestLegacySearchMarker:
    @pytest.mark.parametrize("text,query", [
        ("SEARCH: курс доллара", "курс доллара"),
        ("Jarvis: SEARCH: Эдуард Гунштейн", "Эдуард Гунштейн"),
        ("[SEARCH: Киев новости]", "Киев новости"),
        ("Секунду, bro. SEARCH: правила игры X", "правила игры X"),
        ("search: lowercase is ordinary text", None),
        ("обычный ответ", None),
        ("", None),
    ])
    def test_extract(self, text, query):
        assert MoltbotHandlers._extract_search_query(text) == query

    def test_strip_whole_line(self):
        assert MoltbotHandlers._strip_search_markers("SEARCH: курс доллара") == ""
        assert MoltbotHandlers._strip_search_markers("Jarvis: SEARCH: x\nа вот и ответ") == "а вот и ответ"

    def test_strip_inline(self):
        out = MoltbotHandlers._strip_search_markers("Секунду, bro. SEARCH: правила игры X")
        assert out == "Секунду, bro."
        assert "SEARCH" not in out


class TestRoutedNeverLeaksMarker:
    def _routed_handler(self, reply):
        h = _handler()
        h._call_persona = AsyncMock(return_value=reply)
        h._call_gemini_text = AsyncMock(side_effect=Exception("no gemini"))
        return h

    @pytest.mark.asyncio
    async def test_marker_only_reply_with_failed_search_raises(self, monkeypatch):
        monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
        h = self._routed_handler("SEARCH: что-то")
        h._brave_search = AsyncMock(return_value="")
        with pytest.raises(_AIConnectionError):
            await h._ask_moltbot_routed("Макс", "что-то?", "", None)

    @pytest.mark.asyncio
    async def test_marker_with_text_is_stripped(self, monkeypatch):
        monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
        h = self._routed_handler("Ща гляну. SEARCH: что-то")
        h._brave_search = AsyncMock(return_value="")
        out = await h._ask_moltbot_routed("Макс", "что-то?", "", None)
        assert "SEARCH" not in out and out == "Ща гляну."

    @pytest.mark.asyncio
    async def test_marker_resolved_via_search(self, monkeypatch):
        monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
        h = _handler()
        h._call_persona = AsyncMock(side_effect=["SEARCH: курс доллара", "41.5 грн"])
        out = await h._ask_moltbot_routed("Макс", "курс?", "", None)
        assert out == "41.5 грн"


@pytest.fixture
def brave_state(monkeypatch):
    """Isolate the process-wide Brave throttle/cache and make the pacing test-fast."""
    MoltbotHandlers._brave_cache.clear()
    MoltbotHandlers._brave_last_call = 0.0
    MoltbotHandlers._brave_lock = None
    MoltbotHandlers._brave_lock_loop = None
    monkeypatch.setattr(MoltbotHandlers, "_BRAVE_MIN_INTERVAL", 0.05)
    monkeypatch.setattr(MoltbotHandlers, "_BRAVE_RETRY_DELAY", 0.01)
    monkeypatch.setattr(_mod.Settings, "BRAVE_API_KEY", "k", raising=False)
    yield
    MoltbotHandlers._brave_cache.clear()
    MoltbotHandlers._brave_last_call = 0.0
    MoltbotHandlers._brave_lock = None
    MoltbotHandlers._brave_lock_loop = None


def _http_error(status):
    request = _mod.httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    response = _mod.httpx.Response(status, request=request)
    return _mod.httpx.HTTPStatusError(f"{status}", request=request, response=response)


class TestBraveThrottle:
    """Brave free tier is ~1 req/s and the model fires searches in batches."""

    @pytest.mark.asyncio
    async def test_calls_are_spaced_out(self, brave_state):
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(return_value="- res")
        t0 = _mod.time.monotonic()
        for q in ("a", "b", "c"):
            await h._brave_search(q)
        elapsed = _mod.time.monotonic() - t0
        assert h._brave_request.await_count == 3
        # three calls → at least two gaps of _BRAVE_MIN_INTERVAL
        assert elapsed >= 2 * MoltbotHandlers._BRAVE_MIN_INTERVAL

    @pytest.mark.asyncio
    async def test_repeat_query_served_from_cache(self, brave_state):
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(return_value="- res")
        first = await h._brave_search("Эдуардо Гундини")
        second = await h._brave_search("  эдуардо   ГУНДИНИ ")  # same query, sloppier
        assert first == second == "- res"
        h._brave_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_429_is_retried_once(self, brave_state):
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(side_effect=[_http_error(429), "- res"])
        assert await h._brave_search("курс") == "- res"
        assert h._brave_request.await_count == 2

    @pytest.mark.asyncio
    async def test_429_twice_gives_up_quietly(self, brave_state):
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(side_effect=[_http_error(429), _http_error(429)])
        assert await h._brave_search("курс") == ""
        assert h._brave_request.await_count == 2
        assert MoltbotHandlers._brave_cache == {}  # a rate-limited miss is not cached

    @pytest.mark.asyncio
    async def test_other_http_error_is_not_retried(self, brave_state):
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(side_effect=_http_error(500))
        assert await h._brave_search("курс") == ""
        h._brave_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_api_key_short_circuits(self, brave_state, monkeypatch):
        monkeypatch.setattr(_mod.Settings, "BRAVE_API_KEY", "", raising=False)
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(return_value="- res")
        assert await h._brave_search("курс") == ""
        h._brave_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_is_bounded(self, brave_state, monkeypatch):
        monkeypatch.setattr(MoltbotHandlers, "_BRAVE_CACHE_MAX", 3)
        monkeypatch.setattr(MoltbotHandlers, "_BRAVE_MIN_INTERVAL", 0.0)
        h = MoltbotHandlers.__new__(MoltbotHandlers)
        h._brave_request = AsyncMock(return_value="- res")
        for q in ("a", "b", "c", "d"):
            await h._brave_search(q)
        assert len(MoltbotHandlers._brave_cache) == 3
        assert "a" not in MoltbotHandlers._brave_cache  # oldest evicted


class TestSearchBudget:
    """A reply may spend ~10s on searching; whatever doesn't fit is skipped."""

    @pytest.mark.asyncio
    async def test_call_past_deadline_is_skipped(self):
        h = _handler()
        out = await h._execute_tool_call(
            {"function": {"name": "web_search", "arguments": json.dumps({"query": "курс"})}},
            deadline=_mod.time.monotonic() - 1,
        )
        assert "пропущен" in out
        h._brave_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_within_deadline_runs(self):
        h = _handler()
        out = await h._execute_tool_call(
            {"function": {"name": "web_search", "arguments": json.dumps({"query": "курс"})}},
            deadline=_mod.time.monotonic() + 10,
        )
        assert "Результаты поиска" in out
        h._brave_search.assert_awaited_once_with("курс")

    @pytest.mark.asyncio
    async def test_budget_is_shared_by_the_whole_reply(self, monkeypatch):
        """A batch that eats the budget leaves the later calls skipped, not queued."""
        monkeypatch.setattr(MoltbotHandlers, "_SEARCH_TIME_BUDGET", 0.05)
        h = _handler()

        async def slow_search(query):
            await asyncio.sleep(0.06)
            return "- res"

        h._brave_search = AsyncMock(side_effect=slow_search)
        post = AsyncMock(side_effect=[
            _resp(None, [_tool_call("a", "c1"), _tool_call("b", "c2"), _tool_call("c", "c3")]),
            _resp("ответ"),
        ])
        out = await h._complete_with_tools(post, {"model": "m", "messages": []}, 10)
        assert out == "ответ"
        assert h._brave_search.await_count == 1  # budget spent on the first one
        tool_msgs = [m for m in post.await_args_list[1].args[0]["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) == 3
        assert "пропущен" in tool_msgs[1]["content"] and "пропущен" in tool_msgs[2]["content"]
