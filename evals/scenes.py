"""Golden eval scenes: an immutable input snapshot plus expected *behaviour*.

A scene never stores "the ideal reply" — only criteria a good reply meets and
things it must not do, so different models can be judged on the same input.
Real production scenes live in data/evals/ (gitignored: private chat content);
hand-written targeted scenes live in evals/seed_scenes.jsonl.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data", "evals")
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed_scenes.jsonl")

CATEGORIES = (
    "banter",           # обычный дружеский трёп
    "absurd_bit",       # абсурдный бит — продолжать premise
    "roast_request",    # просят подколоть/зароастить
    "useful_answer",    # практический вопрос, нужна польза
    "factual_fresh",    # внешний свежий факт — поиск уместен
    "local_term",       # внутряк/прозвище — поиск НЕ нужен
    "serious",          # реально серьёзная тема
    "emotional",        # поддержка, эмоции
    "refusal_request",  # просят то, что стоит мягко отклонить
    "correction",       # бота поправляют — признать ошибку
    "self_reference",   # про собственное прошлое сообщение/биографию бота
    "attribution",      # слова одного участника о другом
    "date_time",        # важна текущая дата/время
    "memory_recall",    # уместно/неуместно вспомнить память
    "feature_overlay",  # ивент-оверлей не ломает grounding
    "other",
)

CALLBACK_POLICIES = ("none", "allowed", "expected")


@dataclass
class Expect:
    criteria: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    no_search: bool = False
    callback_policy: str = "allowed"
    max_chars: int = 600


@dataclass
class Scene:
    id: str
    category: str
    at: str                               # ISO time of the trigger (drives the frozen clock)
    trigger_sender: str
    trigger_text: str
    history: list[str] = field(default_factory=list)
    chat_context: str = "групповой чат"
    summary: str = ""
    lore: str = ""
    overlay: str = ""
    prompt_version: int | None = None     # identity version live at that moment (None = current)
    expect: Expect = field(default_factory=Expect)
    reference: dict[str, Any] = field(default_factory=dict)   # prod reply, reactions, signal
    source: str = "prod"                  # prod | seed
    version: int = 1
    notes: str = ""

    def validate(self) -> list[str]:
        problems = []
        if self.category not in CATEGORIES:
            problems.append(f"{self.id}: unknown category {self.category!r}")
        if self.expect.callback_policy not in CALLBACK_POLICIES:
            problems.append(f"{self.id}: bad callback_policy {self.expect.callback_policy!r}")
        if not self.trigger_text.strip():
            problems.append(f"{self.id}: empty trigger")
        if not self.expect.criteria:
            problems.append(f"{self.id}: no criteria")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        data = dict(data)
        data["expect"] = Expect(**(data.get("expect") or {}))
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in known})


def load_jsonl(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_jsonl(path: str, rows: Iterable[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def load_scenes(*paths: str) -> list[Scene]:
    scenes: list[Scene] = []
    for path in paths:
        scenes.extend(Scene.from_dict(row) for row in load_jsonl(path))
    ids = [s.id for s in scenes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate scene ids: {sorted(dupes)}")
    return scenes
