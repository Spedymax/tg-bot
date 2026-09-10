"""Tests for the web_search tool loop and the legacy SEARCH: safety net."""
import sys, os, importlib.util, types, json

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
