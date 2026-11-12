import asyncio
import logging
import sqlite3
from datetime import date, datetime, time, timedelta

from aiogram import Bot
from aiogram.types import FSInputFile

from .config import TargetConfig
from .schedule import build_schedule, demand

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


def queues(conn: sqlite3.Connection, target: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT id, kind FROM posts WHERE target = ? AND sent = 0 AND publish_at IS NULL ORDER BY id", (target,)
    ):
        result.setdefault(row["kind"], []).append(row["id"])
    return result


def slot_times(first: time, last: time, count: int) -> list[time]:
    if count <= 1:
        return [first]
    start = datetime.combine(date.min, first)
    span = datetime.combine(date.min, last) - start
    return [(start + span * i / (count - 1)).time() for i in range(count)]


def schedule_month(conn: sqlite3.Connection, cfg: TargetConfig, start: date,
                   first: time = time(9), last: time = time(21)) -> tuple[int, dict[str, int]]:
    """Assigns publish times to queued posts for one month. Returns (scheduled, shortage by kind)."""
    available = queues(conn, cfg.name)
    slots = build_schedule(start, cfg.weekly, available, cfg.fallbacks)

    per_day: dict[date, list] = {}
    for slot in slots:
        per_day.setdefault(slot.day, []).append(slot)
    with conn:
        for day, day_slots in per_day.items():
            times = slot_times(first, last, len(cfg.weekly.get(day.weekday(), [])))
            for slot in day_slots:
                at = datetime.combine(day, times[slot.index]).isoformat(timespec="minutes")
                conn.execute("UPDATE posts SET publish_at = ? WHERE id = ?", (at, slot.post_id))

    need = demand(start, cfg.weekly)
    have = {kind: len(ids) for kind, ids in available.items()}
    shortage = {kind: n - have.get(kind, 0) for kind, n in need.items() if n > have.get(kind, 0)}
    return len(slots), shortage


async def send(bot: Bot, chat_id: str, post: sqlite3.Row) -> None:
    text = post["text"] or None
    if post["image_path"]:
        if text and len(text) > CAPTION_LIMIT:
            await bot.send_photo(chat_id, FSInputFile(post["image_path"]))
            await bot.send_message(chat_id, text)
        else:
            await bot.send_photo(chat_id, FSInputFile(post["image_path"]), caption=text)
    elif text:
        await bot.send_message(chat_id, text)


async def publish_due(conn: sqlite3.Connection, bot: Bot, cfg: TargetConfig, now: datetime | None = None) -> int:
    """Sends every post whose time has come. Meant to be run from cron every few minutes."""
    now = (now or datetime.now()).isoformat(timespec="minutes")
    due = conn.execute(
        "SELECT * FROM posts WHERE target = ? AND sent = 0 AND publish_at <= ? ORDER BY publish_at, id",
        (cfg.name, now),
    ).fetchall()
    sent = 0
    for post in due:
        try:
            await send(bot, cfg.chat_id, post)
        except Exception as exc:
            log.warning("post %s not sent: %s", post["id"], exc)
            continue
        conn.execute("UPDATE posts SET sent = 1 WHERE id = ?", (post["id"],))
        conn.commit()
        sent += 1
        await asyncio.sleep(1)
    return sent


def next_free_day(conn: sqlite3.Connection, target: str) -> date:
    row = conn.execute("SELECT MAX(publish_at) FROM posts WHERE target = ?", (target,)).fetchone()[0]
    if row:
        return datetime.fromisoformat(row).date() + timedelta(days=1)
    return date.today() + timedelta(days=1)
