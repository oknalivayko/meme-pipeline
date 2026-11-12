import json
import sqlite3
from pathlib import Path

LAUGH_EMOJI = {"😂", "🤣", "😁", "😆", "😹", "😄", "😃"}


def flatten_text(raw) -> str:
    if isinstance(raw, str):
        return raw.strip()
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in raw or []).strip()


def parse_reactions(raw) -> tuple[dict[str, int], int, int]:
    breakdown: dict[str, int] = {}
    for r in raw or []:
        key = r.get("emoji") or r.get("document_id") or r.get("type", "other")
        breakdown[key] = breakdown.get(key, 0) + r.get("count", 0)
    total = sum(breakdown.values())
    laugh = sum(count for emoji, count in breakdown.items() if emoji in LAUGH_EMOJI)
    return breakdown, total, laugh


def import_export(conn: sqlite3.Connection, export_file: Path) -> int:
    """Adds new posts from one export. Already imported posts are skipped, so exports can be refreshed."""
    data = json.loads(export_file.read_text(encoding="utf-8"))
    source = data.get("name") or export_file.parent.name
    base = export_file.parent

    rows = []
    for msg in data.get("messages", []):
        if msg.get("type") != "message" or "date" not in msg:
            continue
        photo = msg.get("photo")
        if photo and not (base / photo).exists():
            photo = None
        text = flatten_text(msg.get("text"))
        if not photo and not text:
            continue
        breakdown, total, laugh = parse_reactions(msg.get("reactions"))
        rows.append((
            source, msg["id"], msg["date"], msg["date"][:7], text,
            str((base / photo).resolve()) if photo else None,
            json.dumps(breakdown, ensure_ascii=False), total, laugh,
        ))

    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO memes
            (source, post_id, date, year_month, text, photo_path, reactions, total_reactions, laugh_reactions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return conn.total_changes - before
