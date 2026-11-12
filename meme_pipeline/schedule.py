"""Monthly publishing grid.

Every weekday has a fixed list of slots ("meme", "quote", "story"...). A month
is counted from any start date to the day before the same date next month.
When a content type runs out, its slot is filled with the type that has the
most posts left among the configured fallbacks, so the grid never has holes as
long as there is content at all.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Slot:
    day: date
    index: int
    kind: str
    post_id: int


def add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def month_days(start: date) -> list[date]:
    end = add_month(start)
    return [start + timedelta(days=i) for i in range((end - start).days)]


def build_schedule(
    start: date,
    weekly: dict[int, list[str]],
    queues: dict[str, list[int]],
    fallbacks: dict[str, list[str]] | None = None,
) -> list[Slot]:
    """weekly: weekday (0 = Monday) -> slot kinds; queues: kind -> post ids in publishing order."""
    queues = {kind: list(ids) for kind, ids in queues.items()}
    fallbacks = fallbacks or {}
    slots = []
    for day in month_days(start):
        for index, kind in enumerate(weekly.get(day.weekday(), [])):
            chosen = kind
            if not queues.get(kind):
                options = [k for k in fallbacks.get(kind, []) if queues.get(k)]
                if not options:
                    continue
                chosen = max(options, key=lambda k: len(queues[k]))
            slots.append(Slot(day, index, chosen, queues[chosen].pop(0)))
    return slots


def demand(start: date, weekly: dict[int, list[str]]) -> dict[str, int]:
    """How many posts of each kind a month starting at `start` needs."""
    need: dict[str, int] = {}
    for day in month_days(start):
        for kind in weekly.get(day.weekday(), []):
            need[kind] = need.get(kind, 0) + 1
    return need
