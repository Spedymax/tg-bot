import pytest


def pytest_collection_modifyitems(items):
    """Auto-mark all async test functions with pytest.mark.asyncio."""
    for item in items:
        if item.get_closest_marker("asyncio") is None:
            if hasattr(item, "function") and __import__("asyncio").iscoroutinefunction(item.function):
                item.add_marker(pytest.mark.asyncio)


@pytest.fixture(autouse=True)
def _no_real_llm_keys(monkeypatch):
    """Tests must never reach paid providers. Run from the prod checkout, config.settings loads the
    real .env (OpenRouter/Together/Gemini keys) and fallback chains would make live, billed calls.
    A test that needs a key sets a fake one explicitly (monkeypatch.setattr(..., "x"))."""
    import os
    import sys
    src = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
    # src/ must win over the repo root: pytest puts the root first (tests/ is a package), and the root's
    # legacy config.py (scripts/songs.py) would shadow the src/config package for every later test.
    sys.path[:] = [src] + [p for p in sys.path if os.path.normpath(p or ".") != src]
    if not hasattr(sys.modules.get("config"), "__path__"):
        sys.modules.pop("config", None)
    try:
        from config.settings import Settings
    except Exception:
        return
    for name in ("OPENROUTER_API_KEY", "TOGETHER_API_KEY", "GEMINI_API_KEY", "BRAVE_API_KEY"):
        if hasattr(Settings, name):
            monkeypatch.setattr(Settings, name, None, raising=False)
