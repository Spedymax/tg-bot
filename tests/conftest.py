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
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        from config.settings import Settings
    except Exception:
        return
    for name in ("OPENROUTER_API_KEY", "TOGETHER_API_KEY", "GEMINI_API_KEY", "BRAVE_API_KEY"):
        if hasattr(Settings, name):
            monkeypatch.setattr(Settings, name, None, raising=False)
