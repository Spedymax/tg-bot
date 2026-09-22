"""Per-reply LLM telemetry: one trace per persona reply, carried via contextvars.

A trace records what the model actually saw and how the reply was produced:
prompt version, context section sizes, every provider attempt (model, upstream
provider, usage/cost, latency, error), tool calls and the final outcome. It is
logged as one JSON line and stored in `llm_traces` so prompt/model/memory
changes can be compared on real traffic instead of vibes.

Telegram IDs never leave the server in the clear: providers only get opaque
hashes (`opaque_id`).
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_current: contextvars.ContextVar["LLMTrace | None"] = contextvars.ContextVar("llm_trace", default=None)

# Stable per-install salt so hashes can't be reversed by brute-forcing chat ids.
_SALT = os.getenv("LLM_TRACE_SALT") or os.getenv("JARVIS_TOKEN") or "jarvis-trace"

CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS llm_traces ("
    " trace_id TEXT PRIMARY KEY,"
    " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
    " chat_id BIGINT,"
    " kind TEXT NOT NULL,"
    " prompt_version INTEGER,"
    " reasoning TEXT,"
    " final_model TEXT,"
    " final_provider TEXT,"
    " outcome TEXT,"
    " latency_ms INTEGER,"
    " prompt_tokens INTEGER,"
    " completion_tokens INTEGER,"
    " cost_usd DOUBLE PRECISION,"
    " search_calls INTEGER NOT NULL DEFAULT 0,"
    " reply_chars INTEGER,"
    " data JSONB NOT NULL DEFAULT '{}')"
)
CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS llm_traces_chat_created_idx ON llm_traces (chat_id, created_at DESC)"


def opaque_id(*parts: Any) -> str:
    """Short salted hash for provider-facing identifiers (session/user)."""
    raw = ":".join(str(p) for p in (_SALT, *parts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass
class Attempt:
    provider: str
    model: str
    ok: bool = False
    latency_ms: int = 0
    error: str = ""
    upstream: str = ""
    request_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class LLMTrace:
    kind: str
    chat_id: int | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    prompt_version: int | None = None
    reasoning: str = ""
    sections: dict[str, int] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    memory_mode: str = ""
    memory_ids: list[int] = field(default_factory=list)
    outcome: str = "pending"
    reply_chars: int = 0
    started: float = field(default_factory=time.monotonic)
    latency_ms: int = 0

    # ── recording helpers ───────────────────────────────────────────────
    def start_attempt(self, provider: str, model: str) -> Attempt:
        attempt = Attempt(provider=provider, model=model)
        self.attempts.append(attempt)
        return attempt

    def record_tool(self, name: str, reason: str, ok: bool, latency_ms: int) -> None:
        self.tools.append({"name": name, "reason": reason, "ok": ok, "latency_ms": latency_ms})

    def finish(self, outcome: str, reply: str | None = None) -> None:
        self.outcome = outcome
        self.reply_chars = len(reply or "")
        self.latency_ms = int((time.monotonic() - self.started) * 1000)

    # ── derived ─────────────────────────────────────────────────────────
    @property
    def final_attempt(self) -> Attempt | None:
        for attempt in reversed(self.attempts):
            if attempt.ok:
                return attempt
        return self.attempts[-1] if self.attempts else None

    def totals(self) -> tuple[int, int, float]:
        return (
            sum(a.prompt_tokens for a in self.attempts),
            sum(a.completion_tokens for a in self.attempts),
            round(sum(a.cost_usd for a in self.attempts), 6),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("started", None)
        return data


def current() -> LLMTrace | None:
    return _current.get()


def begin(kind: str, chat_id: int | None) -> tuple[LLMTrace, contextvars.Token]:
    trace = LLMTrace(kind=kind, chat_id=chat_id)
    return trace, _current.set(trace)


def end(token: contextvars.Token) -> None:
    _current.reset(token)


def apply_response(attempt: Attempt | None, data: dict[str, Any]) -> None:
    """Copy usage/cost/upstream info from an OpenAI-style response into the attempt.
    Usage is summed: tool rounds make several requests inside one attempt."""
    if attempt is None or not isinstance(data, dict):
        return
    usage = data.get("usage") or {}
    attempt.prompt_tokens += int(usage.get("prompt_tokens") or 0)
    attempt.completion_tokens += int(usage.get("completion_tokens") or 0)
    try:
        attempt.cost_usd += float(usage.get("cost") or 0)
    except (TypeError, ValueError):
        pass
    attempt.upstream = str(data.get("provider") or attempt.upstream or "")
    attempt.request_id = str(data.get("id") or attempt.request_id or "")
    if data.get("model"):
        attempt.model = str(data["model"])


async def persist(trace: LLMTrace, db) -> None:
    """Log one JSON line and store the trace. Never raises."""
    final = trace.final_attempt
    prompt_tokens, completion_tokens, cost = trace.totals()
    summary = {
        "trace_id": trace.trace_id,
        "kind": trace.kind,
        "chat": opaque_id("chat", trace.chat_id) if trace.chat_id is not None else None,
        "prompt_v": trace.prompt_version,
        "route": [f"{a.provider}:{a.model}:{'ok' if a.ok else 'fail'}" for a in trace.attempts],
        "outcome": trace.outcome,
        "ms": trace.latency_ms,
        "tok": [prompt_tokens, completion_tokens],
        "cost": cost,
        "tools": len(trace.tools),
        "sections": trace.sections,
        "mem": trace.memory_ids,
    }
    logger.info("LLM_TRACE %s", json.dumps(summary, ensure_ascii=False))
    if db is None:
        return
    try:
        await db.execute_query(
            "INSERT INTO llm_traces (trace_id, chat_id, kind, prompt_version, reasoning, final_model, "
            "final_provider, outcome, latency_ms, prompt_tokens, completion_tokens, cost_usd, "
            "search_calls, reply_chars, data) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (trace_id) DO NOTHING",
            (
                trace.trace_id, trace.chat_id, trace.kind, trace.prompt_version, trace.reasoning,
                final.model if final else None,
                (final.upstream or final.provider) if final else None,
                trace.outcome, trace.latency_ms, prompt_tokens, completion_tokens, cost,
                sum(1 for t in trace.tools if t["name"] == "web_search"),
                trace.reply_chars,
                json.dumps(trace.to_dict(), ensure_ascii=False),
            ),
        )
    except Exception as e:
        logger.warning(f"LLM trace persist failed: {e}")


async def ensure_table(db) -> None:
    try:
        await db.execute_query(CREATE_TABLE_SQL)
        await db.execute_query(CREATE_INDEX_SQL)
    except Exception as e:
        logger.warning(f"LLM trace table setup failed: {e}")


def persist_in_background(trace: LLMTrace, db) -> None:
    try:
        asyncio.get_running_loop().create_task(persist(trace, db))
    except RuntimeError:
        pass
