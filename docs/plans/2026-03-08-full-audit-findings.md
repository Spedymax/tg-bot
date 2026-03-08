# Full Codebase Audit — 2026-03-08

## Overall Score: 5.6/10

---

## Critical Issues (Fix Immediately)

| # | Issue | Location | Risk |
|---|-------|----------|------|
| 1 | SQL Injection — `INTERVAL '%s hours'` not safely parameterized | `admin_handlers.py:97-98` | Data breach |
| 2 | Plaintext passwords — no hashing in DB | `memories.py:243-276` | Credential theft |
| 3 | Duplicate handler — `show_items()` defined twice | `shop_handlers.py:37-60, 88-100` | Silent bugs |
| 4 | Bug — `bot.reply_to(message, message)` sends object not text | `songs.py:85` | Crash |
| 5 | 12+ `print()` instead of `logger.error()` | `db_manager.py:108`, `admin_handlers.py:207`, `trivia_handlers.py` (10 instances) | Lost error logs |
| 6 | No startup validation — missing token = None, crashes later | `settings.py:16` | Boot failure |

---

## Architecture Pain Points

| Area | Problem | Impact |
|------|---------|--------|
| **Sync DB in async bot** | 50+ `asyncio.to_thread()` calls wrapping psycopg2 | Thread pool saturation under load |
| **Mixed frameworks** | aiogram v3 (main), pyTelegramBotAPI (memories, btc, songs), Pyrogram (love) | 3x maintenance burden |
| **In-memory cache** | PlayerService dict cache not shared across Gunicorn workers | Stale data, wasted memory |
| **No circuit breaker** | Ollama/Gemini failures cascade into hung handlers | Bot goes unresponsive |
| **Broad exception handling** | 25+ bare `except Exception` blocks swallow errors | Silent failures |

---

## Code Quality Metrics

| Metric | Status |
|--------|--------|
| Type hints | ~40% coverage, no mypy enforcement |
| Tests | 3.2K lines, all mock-heavy, no integration/async tests |
| Large files | moltbot_handlers (1132), court_handlers (962), admin_handlers (952), memories (1404) |
| Logging | Good rotation, but print() scattered in 12+ places |
| Dependencies | Pillow 10.4 (CVEs), certifi outdated, openai loosely pinned |

---

## Modernization Roadmap

### Phase 1: Async Database (IN PROGRESS — branch: refactor/async-db)
- Replace psycopg2 with asyncpg
- Eliminate all `asyncio.to_thread()` DB wrappers
- Migrate PlayerService to async
- Migrate DatabaseManager to async connection pool

### Phase 2: Fix Critical Bugs
- SQL injection in admin_handlers
- Plaintext passwords in memories.py
- Duplicate handler in shop_handlers
- Bug in songs.py:85
- Replace print() with logger.error()
- Add startup config validation

### Phase 3: Architecture Cleanup
- Consolidate to aiogram v3 (migrate memories, btc, songs off pyTelegramBotAPI)
- Move PlayerService cache to Redis (already have Redis for FSM)
- Add circuit breakers for Ollama/Gemini/Spotify
- Break large handler files into focused modules

### Phase 4: Quality & Testing
- Add type hints + mypy strict
- Add pytest-asyncio for handler tests
- Integration tests with real DB
- Update vulnerable dependencies

### Phase 5: Observability
- Structured JSON logging
- Request correlation/tracing
- Prometheus metrics
- Health monitoring with alerts
