"""Telegram bot for manual meme curation.

The editor picks a target channel and gets candidates one by one with
Approve / Reject buttons. Reposts of already reviewed images never reach the
editor: the selector rejects them by perceptual hash.
"""
import logging
from contextlib import suppress

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import TargetConfig
from .selection import Selector

log = logging.getLogger(__name__)


class AdminOnly(BaseMiddleware):
    def __init__(self, admin_ids: frozenset[int]):
        self.admin_ids = admin_ids

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id not in self.admin_ids:
            return None
        return await handler(event, data)


def buttons(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows
    ])


class CuratorBot:
    def __init__(self, conn, token: str, admin_ids: frozenset[int], targets: dict[str, TargetConfig]):
        self.conn = conn
        self.targets = targets
        self.bot = Bot(token)
        self.dp = Dispatcher()
        self.selectors: dict[int, Selector] = {}
        self.pending: dict[int, tuple[int, int]] = {}

        self.dp.update.outer_middleware(AdminOnly(admin_ids))
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.callback_query.register(self.on_target, F.data.startswith("target:"))
        self.dp.callback_query.register(self.on_decision, F.data.startswith(("approve:", "reject:")))

    async def cmd_start(self, message: Message) -> None:
        await message.answer(
            "Choose a channel to curate for:",
            reply_markup=buttons(*[[(name, f"target:{name}")] for name in self.targets]),
        )

    async def cmd_stats(self, message: Message) -> None:
        lines = []
        for name in self.targets:
            counts = dict(self.conn.execute(
                "SELECT decision, COUNT(*) FROM decisions WHERE target = ? GROUP BY decision", (name,)
            ).fetchall())
            unsent = self.conn.execute(
                "SELECT COUNT(*) FROM posts WHERE target = ? AND sent = 0", (name,)
            ).fetchone()[0]
            summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nothing reviewed"
            lines.append(f"{name}\n  {summary}\n  queued posts: {unsent}")
        await message.answer("\n\n".join(lines))

    async def on_target(self, cb: CallbackQuery) -> None:
        name = cb.data.split(":", 1)[1]
        self.selectors[cb.from_user.id] = Selector(self.conn, self.targets[name].target)
        await cb.answer()
        await self.show_next(cb.message.chat.id, cb.from_user.id)

    async def show_next(self, chat_id: int, user_id: int) -> None:
        selector = self.selectors[user_id]
        found = selector.next_candidate()
        if found is None:
            await self.bot.send_message(chat_id, "No candidates left for this channel.")
            return
        meme, image_hash = found
        self.pending[user_id] = (meme["id"], image_hash)
        score = meme[selector.target.score_field]
        caption = f"{meme['source']} · {meme['date'][:10]} · score {score:.2f}"
        if meme["text"]:
            caption += f"\n\n{meme['text'][:800]}"
        await self.bot.send_photo(
            chat_id, FSInputFile(meme["photo_path"]), caption=caption,
            reply_markup=buttons([("Approve", f"approve:{meme['id']}"), ("Reject", f"reject:{meme['id']}")]),
        )

    async def on_decision(self, cb: CallbackQuery) -> None:
        action, meme_id = cb.data.split(":")
        user_id = cb.from_user.id
        pending = self.pending.get(user_id)
        if not pending or pending[0] != int(meme_id):
            await cb.answer("Already handled")
            return
        del self.pending[user_id]

        selector = self.selectors[user_id]
        selector.record(int(meme_id), action + "d", pending[1])
        if action == "approve":
            meme = self.conn.execute("SELECT photo_path FROM memes WHERE id = ?", (meme_id,)).fetchone()
            self.conn.execute(
                "INSERT INTO posts (target, kind, image_path, source_meme_id) VALUES (?, 'meme', ?, ?)",
                (selector.target.name, meme["photo_path"], meme_id),
            )
            self.conn.commit()

        await cb.answer("Approved" if action == "approve" else "Rejected")
        with suppress(Exception):
            await cb.message.edit_reply_markup(reply_markup=None)
        await self.show_next(cb.message.chat.id, user_id)

    async def start(self) -> None:
        await self.dp.start_polling(self.bot)
