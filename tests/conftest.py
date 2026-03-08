import pytest


def pytest_collection_modifyitems(items):
    """Auto-mark all async test functions with pytest.mark.asyncio."""
    for item in items:
        if item.get_closest_marker("asyncio") is None:
            if hasattr(item, "function") and __import__("asyncio").iscoroutinefunction(item.function):
                item.add_marker(pytest.mark.asyncio)
