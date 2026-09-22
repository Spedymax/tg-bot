"""Prompt-assembly checks for the daily prophecy.

The bug this guards: the model was left to pick its own subject matter and picked the
same two every day (a dropped phone + greasy food, 20 of 24 lines in one week). The
fix assigns a life domain per person and refuses to repeat yesterday's prophet voice,
so what's worth asserting is that both actually reach the prompt.
"""
import asyncio
import sys
import types
from pathlib import Path

# Load the module straight from its path with a stubbed `handlers` package: importing it
# normally executes handlers/__init__.py, which drags in the whole DB/bot/spotify stack.
import importlib.util

_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

_pkg = types.ModuleType("handlers")
_pkg.__path__ = [str(_SRC / "handlers")]
sys.modules["handlers"] = _pkg
_molt = types.ModuleType("handlers.moltbot_handlers")
_molt.CHAT_LORE_PATH = "/dev/null"
sys.modules["handlers.moltbot_handlers"] = _molt

_spec = importlib.util.spec_from_file_location(
    "handlers.daily_prophecy_handlers", _SRC / "handlers" / "daily_prophecy_handlers.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

DailyProphecyHandlers = _mod.DailyProphecyHandlers
LIFE_DOMAINS = _mod.LIFE_DOMAINS
PROPHET_STYLES = _mod.PROPHET_STYLES
FORMAT_FLAVORS = _mod.FORMAT_FLAVORS
STORY_MODES = _mod.STORY_MODES
MAX_PROPHECY_WORDS = _mod.MAX_PROPHECY_WORDS
MAX_SCENE_WORDS = _mod.MAX_SCENE_WORDS


class _Probe(DailyProphecyHandlers):
    """Captures the prompt instead of calling an LLM."""

    def __init__(self):
        self.prompts = []
        self._gemini = None

    async def _call_llm(self, system_prompt, user_prompt):
        self.prompts.append((system_prompt, user_prompt))
        return "Сцена.\n\nМакс: раз\nЮра: два\nБогдан: три"


PEOPLE = [(1, "Макс", "вчерашний текст"), (2, "Юра", ""), (3, "Богдан", "ещё текст")]


def test_each_person_gets_a_domain():
    probe = _Probe()
    style, scene, prophecies, meta = asyncio.run(probe._generate_prophecies(PEOPLE, lore=""))
    prompt = probe.prompts[0][1]
    assert len(prophecies) == 3, prophecies
    assert "Сфера жизни" in prompt
    hits = [d for d in LIFE_DOMAINS if d in prompt]
    # Linked mode shares one domain across the chain; otherwise it's one each.
    assert len(hits) in (1, 3), hits


def test_yesterdays_voice_is_skipped():
    probe = _Probe()
    for _ in range(20):
        style, _, _, _ = asyncio.run(
            probe._generate_prophecies(PEOPLE, lore="", exclude_style="doom_prophet")
        )
        assert style["key"] != "doom_prophet"


def test_worn_out_subjects_are_banned():
    probe = _Probe()
    asyncio.run(probe._generate_prophecies(PEOPLE, lore=""))
    system = probe.prompts[0][0]
    for banned in ("телефон как главный объект", "маршрутка", "касса"):
        assert banned in system, banned


def test_recent_generation_choices_are_rotated():
    probe = _Probe()
    history = [
        {"format_key": "rpg", "story_mode": "domino", "outcome_key": "one_lucky", "lucky_user_id": 3},
        {"format_key": "plain", "story_mode": "independent", "outcome_key": "ambiguous", "lucky_user_id": 2},
    ]
    _, _, _, meta = asyncio.run(
        probe._generate_prophecies(PEOPLE, lore="", generation_history=history)
    )
    assert meta["format_key"] not in {"rpg", "plain"}
    assert meta["story_mode"] not in {"domino", "independent"}
    assert meta["outcome_key"] not in {"one_lucky", "ambiguous"}


def test_prophecies_are_hard_limited_even_if_model_rambles():
    shortened = DailyProphecyHandlers._shorten_prophecy("слово " * 100)
    assert len(shortened.split()) <= MAX_PROPHECY_WORDS
    scene = DailyProphecyHandlers._shorten_text("сцена " * 100, MAX_SCENE_WORDS)
    assert len(scene.split()) <= MAX_SCENE_WORDS


def test_variety_pools_are_large_and_have_unique_keys():
    format_keys = [item["key"] for item in FORMAT_FLAVORS]
    story_keys = [item["key"] for item in STORY_MODES]
    assert len(format_keys) >= 12
    assert len(story_keys) >= 10
    assert len(format_keys) == len(set(format_keys))
    assert len(story_keys) == len(set(story_keys))


if __name__ == "__main__":
    test_each_person_gets_a_domain()
    test_yesterdays_voice_is_skipped()
    test_worn_out_subjects_are_banned()
    print(f"ok — {len(LIFE_DOMAINS)} domains, {len(PROPHET_STYLES)} voices")
