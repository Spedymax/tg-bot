"""Identity prompt management: DB-backed versions + admin whitelist.

Source of truth at runtime is `prompt_versions` table. The file
`docs/openclaw-identity-lolita.md` is the seed-default used by bootstrap()
when the table is empty, and the fallback when the DB is unreachable.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from config.settings import Settings
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SEED_IDENTITY_PATH = os.path.join(_BASE_DIR, "docs", "openclaw-identity-lolita.md")


class PromptService:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._cached_identity: str | None = None
        self._cache_version_id: int | None = None

    async def bootstrap(self) -> None:
        """Seed admin and first version if tables are empty. Idempotent."""
        admin_id = getattr(Settings, "ADMIN_USER_ID", None)
        if not admin_id:
            logger.warning("PromptService.bootstrap: ADMIN_USER_ID not set, skipping admin seed")
        else:
            async with self.db.connection() as conn:
                cur = await conn.execute("SELECT COUNT(*) FROM prompt_admins")
                row = await cur.fetchone()
                if row[0] == 0:
                    await conn.execute(
                        "INSERT INTO prompt_admins (user_id, username, granted_by) "
                        "VALUES (%s, %s, NULL)",
                        (int(admin_id), "bootstrap"),
                    )
                    logger.info(f"PromptService.bootstrap: seeded bootstrap admin {admin_id}")

        async with self.db.connection() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM prompt_versions")
            row = await cur.fetchone()
            if row[0] == 0:
                try:
                    with open(_SEED_IDENTITY_PATH, encoding="utf-8") as f:
                        seed = f.read().strip()
                except FileNotFoundError:
                    logger.error(f"PromptService.bootstrap: seed file missing at {_SEED_IDENTITY_PATH}")
                    seed = "Ты — AI-помощник."
                await conn.execute(
                    "INSERT INTO prompt_versions (content, author_id, author_name, note) "
                    "VALUES (%s, %s, %s, %s)",
                    (seed, int(admin_id or 0), "bootstrap", "bootstrap from file"),
                )
                logger.info(f"PromptService.bootstrap: seeded first identity version ({len(seed)} chars)")

    async def get_current_identity(self) -> str:
        """Return latest identity. Cached in-memory. Falls back to seed file on DB error."""
        if self._cached_identity is not None:
            return self._cached_identity
        try:
            async with self.db.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, content FROM prompt_versions ORDER BY created_at DESC LIMIT 1"
                )
                row = await cur.fetchone()
                if row:
                    self._cache_version_id = row[0]
                    self._cached_identity = row[1]
                    return self._cached_identity
        except Exception as e:
            logger.warning(f"PromptService.get_current_identity: DB read failed ({e}), using seed file")
        try:
            with open(_SEED_IDENTITY_PATH, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "Ты — AI-помощник."

    async def set_identity(
        self,
        content: str,
        author_id: int,
        author_name: str | None,
        note: str | None = None,
    ) -> int:
        """Insert new version. Updates cache directly. Returns new version id."""
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO prompt_versions (content, author_id, author_name, note) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (content, int(author_id), author_name, note),
            )
            row = await cur.fetchone()
            new_id = row[0]
        self._cached_identity = content
        self._cache_version_id = new_id
        logger.info(
            f"PromptService.set_identity: v{new_id} by {author_id} ({len(content)} chars) "
            f"preview={content[:80]!r}"
        )
        return new_id

    async def list_versions(self, limit: int = 7) -> list[dict[str, Any]]:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, author_id, author_name, created_at, note, "
                "       LEFT(content, 80) AS preview, LENGTH(content) AS length "
                "FROM prompt_versions ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]

    async def get_version(self, version_id: int) -> dict[str, Any] | None:
        async with self.db.connection() as conn:
            cur = await conn.execute(
                "SELECT id, content, author_id, author_name, created_at, note "
                "FROM prompt_versions WHERE id = %s",
                (int(version_id),),
            )
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
