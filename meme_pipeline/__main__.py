import argparse
import asyncio
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .config import load_targets
from .db import connect
from .ingest import import_export
from .scoring import rescore


def admin_ids() -> frozenset[int]:
    return frozenset(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())


def require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def cmd_ingest(args, conn, targets):
    for export_file in sorted(Path(args.export_dir).rglob("result.json")):
        print(f"{export_file.parent.name}: {import_export(conn, export_file)} new posts")
    print(f"rescored {rescore(conn)} posts")


def cmd_top(args, conn, targets):
    field = args.by
    if field not in {"channel_score", "laugh_score", "global_score"}:
        raise SystemExit("--by must be channel_score, laugh_score or global_score")
    rows = conn.execute(
        f"SELECT source, date, total_reactions, {field} AS score, text FROM memes ORDER BY {field} DESC LIMIT ?",
        (args.limit,),
    )
    for r in rows:
        text = " ".join((r["text"] or "").split())[:70]
        print(f"{r['score']:6.2f}  {r['total_reactions']:6}  {r['date'][:10]}  {r['source'][:24]:24}  {text}")


def cmd_add_text(args, conn, targets):
    blocks = [b.strip() for b in Path(args.file).read_text(encoding="utf-8").split("\n\n") if b.strip()]
    conn.executemany(
        "INSERT INTO posts (target, kind, text) VALUES (?, ?, ?)",
        [(args.target, args.kind, block) for block in blocks],
    )
    conn.commit()
    print(f"added {len(blocks)} '{args.kind}' posts to {args.target}")


def cmd_render(args, conn, targets):
    from .render import add_watermark, chat_bubble

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT id, text FROM posts WHERE target = ? AND kind = ? AND image_path IS NULL AND sent = 0",
        (args.target, args.kind),
    ).fetchall()
    for row in rows:
        image = chat_bubble(row["text"], args.template, args.font)
        add_watermark(image, args.watermark)
        path = out_dir / f"{args.kind}_{row['id']}.png"
        image.convert("RGB").save(path, quality=92)
        conn.execute("UPDATE posts SET image_path = ?, text = NULL WHERE id = ?", (str(path), row["id"]))
    conn.commit()
    print(f"rendered {len(rows)} images into {out_dir}")


def cmd_schedule(args, conn, targets):
    from .publisher import next_free_day, schedule_month

    cfg = targets[args.target]
    start = date.fromisoformat(args.start) if args.start else next_free_day(conn, cfg.name)
    scheduled, shortage = schedule_month(conn, cfg, start)
    print(f"{cfg.name}: {scheduled} posts scheduled from {start}")
    for kind, missing in shortage.items():
        print(f"  not enough '{kind}': {missing} slots were filled by fallbacks or left empty")


def cmd_publish(args, conn, targets):
    from aiogram import Bot

    from .publisher import publish_due

    async def run():
        bot = Bot(require("BOT_TOKEN"))
        try:
            for cfg in targets.values():
                print(f"{cfg.name}: sent {await publish_due(conn, bot, cfg)}")
        finally:
            await bot.session.close()

    asyncio.run(run())


def cmd_curate(args, conn, targets):
    from .curator_bot import CuratorBot

    if not admin_ids():
        raise SystemExit("ADMIN_IDS is not set")
    asyncio.run(CuratorBot(conn, require("BOT_TOKEN"), admin_ids(), targets).start())


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="meme_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="import donor exports and recompute scores")
    p.add_argument("export_dir")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("top", help="print the most viral posts")
    p.add_argument("--by", default="channel_score")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_top)

    p = sub.add_parser("curate", help="run the curation bot")
    p.set_defaults(func=cmd_curate)

    p = sub.add_parser("add-text", help="queue text posts from a file (blocks separated by a blank line)")
    p.add_argument("file")
    p.add_argument("--target", required=True)
    p.add_argument("--kind", required=True)
    p.set_defaults(func=cmd_add_text)

    p = sub.add_parser("render", help="render queued text posts as chat-bubble images")
    p.add_argument("--target", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--out", default="data/rendered")
    p.add_argument("--template")
    p.add_argument("--font", default=os.getenv("FONT_PATH"))
    p.add_argument("--watermark", default=os.getenv("WATERMARK_PATH"))
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("schedule", help="assign publish times for one month")
    p.add_argument("--target", required=True)
    p.add_argument("--start", help="first day, YYYY-MM-DD (default: day after the last scheduled post)")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("publish", help="send posts whose time has come")
    p.set_defaults(func=cmd_publish)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    targets = load_targets(os.getenv("TARGETS_FILE", "targets.json")) if args.command in {"curate", "schedule", "publish"} else {}
    args.func(args, connect(os.getenv("DB_PATH", "data/memes.db")), targets)


if __name__ == "__main__":
    main()
