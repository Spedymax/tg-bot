"""Telegram commands for editing the AI Identity prompt.

All commands require the sender to be in prompt_admins. Non-admins are
silently ignored to avoid spam from random chat members.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile

from services.prompt_service import get_prompt_service

logger = logging.getLogger(__name__)
prompt_router = Router(name="prompt")

_LOCAL_TZ = ZoneInfo("Europe/Copenhagen")
_MIN_LEN = 20
_MAX_LEN = 8000
_TG_TEXT_LIMIT = 4000
_ATTACHMENT_MAX = 16 * 1024  # 16 KB


def _fmt_ts(dt: datetime | None) -> str:
    if not dt:
        return "?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_LOCAL_TZ).strftime("%d.%m %H:%M")


async def _require_admin(message: Message) -> bool:
    """Return True if sender is admin; otherwise log+ignore and return False."""
    ps = get_prompt_service()
    uid = message.from_user.id if message.from_user else 0
    if await ps.is_admin(uid):
        return True
    logger.info(f"prompt_handlers: ignored {message.text!r} from non-admin {uid}")
    return False


async def _send_long(message: Message, text: str, filename: str = "prompt.txt") -> None:
    """Send text inline if short, otherwise as a .txt document."""
    if len(text) <= _TG_TEXT_LIMIT:
        await message.reply(text)
    else:
        await message.reply_document(
            BufferedInputFile(text.encode("utf-8"), filename=filename),
            caption=f"({len(text)} chars)",
        )


async def _resolve_user_id(arg: str) -> tuple[int | None, str | None]:
    """Parse '@username' or numeric id from arg. Returns (user_id, username) or (None, None).

    For @username, looks up in `messages` table (populated by /sho_tam_novogo's
    auto-store). If not seen, returns (None, None) — caller asks for numeric id.
    """
    arg = arg.strip()
    if arg.startswith("@"):
        username = arg[1:]
        ps = get_prompt_service()
        async with ps.db.connection() as conn:
            cur = await conn.execute(
                "SELECT user_id FROM messages WHERE name = %s "
                "ORDER BY timestamp DESC LIMIT 1",
                (username,),
            )
            row = await cur.fetchone()
            if row:
                return int(row[0]), username
            return None, None
    try:
        return int(arg), None
    except ValueError:
        return None, None


@prompt_router.message(Command("prompt"))
async def cmd_prompt(message: Message):
    if not await _require_admin(message):
        return
    text = await get_prompt_service().get_current_identity()
    await _send_long(message, text, filename="identity.md")


@prompt_router.message(Command("setprompt"))
async def cmd_setprompt(message: Message, command: CommandObject):
    if not await _require_admin(message):
        return
    content: str | None = (command.args or "").strip() or None

    # Attachment fallback: .txt or .md document
    if not content and message.document:
        doc = message.document
        name = (doc.file_name or "").lower()
        if not (name.endswith(".txt") or name.endswith(".md")):
            await message.reply("Поддерживаются только .txt / .md файлы")
            return
        if (doc.file_size or 0) > _ATTACHMENT_MAX:
            await message.reply(f"Файл слишком большой (макс {_ATTACHMENT_MAX} байт)")
            return
        file = await message.bot.download(doc)
        content = file.read().decode("utf-8").strip()

    if not content:
        await message.reply(
            "Использование: /setprompt <текст>\n"
            "Или приложи .txt/.md файл с командой /setprompt"
        )
        return
    if len(content) < _MIN_LEN:
        await message.reply(f"Слишком коротко, минимум {_MIN_LEN} символов")
        return
    if len(content) > _MAX_LEN:
        await message.reply(f"Слишком длинно, максимум {_MAX_LEN} символов")
        return

    author = message.from_user
    author_name = (author.username or author.full_name) if author else None
    try:
        new_id = await get_prompt_service().set_identity(
            content, author_id=author.id if author else 0, author_name=author_name
        )
    except Exception as e:
        logger.error(f"setprompt: DB error: {e}")
        await message.reply("Ошибка БД, попробуй позже")
        return
    await message.reply(f"OK, Identity v{new_id} установлен ({len(content)} символов)")


@prompt_router.message(Command("promptlog"))
async def cmd_promptlog(message: Message):
    if not await _require_admin(message):
        return
    versions = await get_prompt_service().list_versions(limit=7)
    if not versions:
        await message.reply("История пуста")
        return
    lines = []
    for v in versions:
        note = f" [{v['note']}]" if v.get("note") else ""
        lines.append(
            f"v{v['id']} — {v.get('author_name') or v['author_id']}, "
            f"{_fmt_ts(v['created_at'])}, {v['length']} симв{note}\n"
            f"  «{v['preview']}…»"
        )
    await message.reply("\n\n".join(lines))


@prompt_router.message(Command("promptshow"))
async def cmd_promptshow(message: Message, command: CommandObject):
    if not await _require_admin(message):
        return
    args = (command.args or "").strip()
    try:
        vid = int(args)
    except ValueError:
        await message.reply("Использование: /promptshow <номер версии>")
        return
    v = await get_prompt_service().get_version(vid)
    if not v:
        await message.reply(f"Версии v{vid} не существует")
        return
    header = (
        f"v{v['id']} — {v.get('author_name') or v['author_id']}, "
        f"{_fmt_ts(v['created_at'])}"
    )
    if v.get("note"):
        header += f" [{v['note']}]"
    await _send_long(message, f"{header}\n\n{v['content']}", filename=f"identity-v{vid}.md")


@prompt_router.message(Command("rollback"))
async def cmd_rollback(message: Message, command: CommandObject):
    if not await _require_admin(message):
        return
    args = (command.args or "").strip()
    if args:
        try:
            target = int(args)
        except ValueError:
            await message.reply("Использование: /rollback [номер версии]")
            return
    else:
        versions = await get_prompt_service().list_versions(limit=2)
        if len(versions) < 2:
            await message.reply("Нет предыдущей версии для отката")
            return
        target = versions[1]["id"]

    author = message.from_user
    author_name = (author.username or author.full_name) if author else None
    new_id = await get_prompt_service().rollback_to(
        target, author_id=author.id if author else 0, author_name=author_name
    )
    if new_id is None:
        await message.reply(f"Версии v{target} не существует")
        return
    await message.reply(f"OK, откатились на v{target}, новая запись v{new_id}")


@prompt_router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject):
    if not await _require_admin(message):
        return
    args = (command.args or "").strip()
    if not args:
        await message.reply("Использование: /grant <user_id или @username>")
        return
    target_id, username = await _resolve_user_id(args)
    if target_id is None:
        await message.reply(
            f"Не могу найти {args} — попроси его написать в чат, "
            "или дай числовой user_id"
        )
        return
    granter = message.from_user.id if message.from_user else 0
    added = await get_prompt_service().grant(target_id, username, granter)
    if added:
        logger.info(f"prompt_handlers: granted {target_id} by {granter}")
        await message.reply(f"OK, {args} (id={target_id}) добавлен в админы")
    else:
        await message.reply(f"{args} уже админ")


@prompt_router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject):
    if not await _require_admin(message):
        return
    args = (command.args or "").strip()
    if not args:
        await message.reply("Использование: /revoke <user_id или @username>")
        return
    target_id, _ = await _resolve_user_id(args)
    if target_id is None:
        await message.reply(f"Не могу найти {args}")
        return
    ok, msg = await get_prompt_service().revoke(target_id)
    await message.reply(f"{args}: {msg}")


@prompt_router.message(Command("admins"))
async def cmd_admins(message: Message):
    if not await _require_admin(message):
        return
    admins = await get_prompt_service().list_admins()
    if not admins:
        await message.reply("Админов нет")
        return
    lines = []
    for a in admins:
        granted = f"by {a['granted_by']}" if a["granted_by"] else "bootstrap"
        uname = f"@{a['username']}" if a.get("username") else ""
        lines.append(f"{a['user_id']} {uname} — {granted}, {_fmt_ts(a['granted_at'])}")
    await message.reply("\n".join(lines))
