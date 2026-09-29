"""Scoped sys.modules stubs for the legacy *_fixed.py tests.

They used to replace aiogram, apscheduler, psycopg2, pytz… at import time — i.e. during collection,
for the whole session — so any test collected after them imported `/mock/aiogram.py`."""
import sys


PROJECT_PACKAGES = ("services", "handlers", "database", "models", "config", "middleware")


def install(mocks: dict) -> callable:
    """Put `mocks` into sys.modules; the returned function restores the previous state and drops
    every module imported while the stubs were active (those are bound to the stubs).
    Project modules already imported by other tests are hidden meanwhile, so the legacy tests
    import them against the stubs, as they did when they ran alone."""
    saved = dict(sys.modules)
    for name in list(sys.modules):
        if name.split(".")[0] in PROJECT_PACKAGES:
            del sys.modules[name]
    sys.modules.update(mocks)

    def restore() -> None:
        for name in list(sys.modules):
            if saved.get(name) is not sys.modules[name]:
                del sys.modules[name]
        sys.modules.update(saved)
    return restore
