"""Tiny async OpenRouter client for evals (usage/cost/latency on every call)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

import httpx

URL = "https://openrouter.ai/api/v1/chat/completions"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
# Evals share the key with production Jarvis; never eat into what prod needs.
PROD_RESERVE_USD = float(os.getenv("EVAL_PROD_RESERVE_USD", "3"))


class BudgetError(RuntimeError):
    pass


def remaining_credits(key: str | None = None) -> float:
    r = httpx.get(CREDITS_URL, headers={"Authorization": f"Bearer {key or api_key()}"}, timeout=20)
    r.raise_for_status()
    data = r.json()["data"]
    return float(data["total_credits"]) - float(data["total_usage"])


def ensure_budget(estimated_usd: float, reserve_usd: float = PROD_RESERVE_USD) -> float:
    """Refuse to start an eval step that would leave less than `reserve_usd` for production."""
    left = remaining_credits()
    if left - estimated_usd < reserve_usd:
        raise BudgetError(
            f"OpenRouter credits left ${left:.2f}; this step needs ~${estimated_usd:.2f} and "
            f"${reserve_usd:.2f} stays reserved for production Jarvis. Top up or lower the scope."
        )
    return left


def api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = "/home/spedymax/tg-bot/.env"
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("OPENROUTER_API_KEY not found")


class OpenRouter:
    def __init__(self, concurrency: int = 4, timeout: float = 180):
        self._sem = asyncio.Semaphore(concurrency)
        self._timeout = timeout
        self._client = httpx.AsyncClient()
        self._key = api_key()
        self.spent_usd = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, payload: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        """POST a chat completion; returns the JSON plus `_latency_ms`. Raises on final failure."""
        last: Exception | None = None
        async with self._sem:
            for attempt in range(retries):
                if attempt:
                    await asyncio.sleep(2 * attempt)
                started = time.monotonic()
                try:
                    r = await self._client.post(
                        URL, headers={"Authorization": f"Bearer {self._key}"},
                        json=payload, timeout=self._timeout,
                    )
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    last = e
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    last = RuntimeError(f"OpenRouter {r.status_code}: {r.text[:200]}")
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:300]}")
                data = r.json()
                if "choices" not in data:
                    last = RuntimeError(f"bad response: {str(data)[:300]}")
                    continue
                data["_latency_ms"] = int((time.monotonic() - started) * 1000)
                try:
                    self.spent_usd += float((data.get("usage") or {}).get("cost") or 0)
                except (TypeError, ValueError):
                    pass
                return data
        raise last or RuntimeError("OpenRouter retries exhausted")


def parse_json_reply(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply (tolerates ```json fences)."""
    text = re.sub(r"<think>.*?(?:</think>|$)", "", text or "", flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    body = match.group(0)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Judges sometimes echo the schema's // comments or leave trailing commas.
        body = re.sub(r"//[^\n\"]*(?=\n)", "", body)
        body = re.sub(r",\s*([}\]])", r"\1", body)
        return json.loads(body)
