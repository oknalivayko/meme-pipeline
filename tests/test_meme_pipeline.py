import random
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageDraw

from meme_pipeline.config import TargetConfig
from meme_pipeline.db import connect
from meme_pipeline.imagehash import HashIndex, dhash, hamming
from meme_pipeline.ingest import import_export, parse_reactions
from meme_pipeline.publisher import schedule_month
from meme_pipeline.render import NBSP, bind_short_words, caption_card, chat_bubble, fit_text, wrap_balanced, wrap_greedy
from meme_pipeline.schedule import add_month, build_schedule, demand, month_days
from meme_pipeline.scoring import compute_scores, rescore
from meme_pipeline.selection import Selector, Target

EXPORTS = Path(__file__).parent.parent / "examples" / "exports"


def loaded(tmp_path):
    conn = connect(tmp_path / "m.db")
    for export_file in sorted(EXPORTS.rglob("result.json")):
        import_export(conn, export_file)
    rescore(conn)
    return conn


def noise_image(seed: int, size=200) -> Image.Image:
    rng = random.Random(seed)
    im = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(im)
    for _ in range(12):
        x, y = rng.randrange(size), rng.randrange(size)
        draw.rectangle((x, y, x + 40, y + 40), fill=tuple(rng.randrange(256) for _ in range(3)))
    return im


def test_parse_reactions_counts_laughs():
    breakdown, total, laugh = parse_reactions([
        {"type": "emoji", "emoji": "😂", "count": 5},
        {"type": "emoji", "emoji": "❤", "count": 3},
        {"type": "custom_emoji", "document_id": "x", "count": 2},
    ])
    assert (total, laugh) == (10, 5)
    assert breakdown["x"] == 2


def test_scores_are_relative_to_channel_and_month():
    rows = [("big", "2024-01", 1000, 0), ("big", "2024-01", 3000, 0), ("small", "2024-01", 10, 5), ("small", "2024-01", 30, 15)]
    scores = compute_scores(rows)
    assert [s.channel for s in scores] == [0.5, 1.5, 0.5, 1.5]
    assert [s.laugh for s in scores] == [0.0, 0.0, 0.5, 1.5]
    assert scores[1].global_ > 2 and scores[3].global_ < 0.1


def test_dhash_survives_resize_and_recompression(tmp_path):
    original = noise_image(1)
    path = tmp_path / "copy.jpg"
    original.resize((150, 150)).save(path, quality=40)
    other = noise_image(2)
    assert hamming(dhash(original), dhash(path)) <= 12
    assert hamming(dhash(original), dhash(other)) > 40


def test_hash_index_returns_closest_match():
    index = HashIndex(threshold=1)
    index.add(1, 0b1111)
    index.add(2, 0b1000)
    assert index.find(0b1001) == 2
    assert index.find(0b0110) is None


def test_ingest_is_incremental(tmp_path):
    conn = loaded(tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM memes").fetchone()[0] == 7
    for export_file in EXPORTS.rglob("result.json"):
        assert import_export(conn, export_file) == 0


def test_selector_skips_reposts_and_respects_threshold(tmp_path):
    conn = loaded(tmp_path)
    target = Target("t", {"Office jokes": 1, "Cat pictures": 1}, score_field="laugh_score", min_score=1.0)
    selector = Selector(conn, target, rng=random.Random(0))

    shown = []
    while (found := selector.next_candidate()) is not None:
        meme, image_hash = found
        shown.append(meme["source"])
        selector.record(meme["id"], "approved", image_hash)

    decisions = dict(conn.execute("SELECT decision, COUNT(*) FROM decisions GROUP BY decision").fetchall())
    assert decisions.get("repost") == 1
    assert all(s for s in shown)
    low = conn.execute("SELECT COUNT(*) FROM memes WHERE laugh_score < 1.0").fetchone()[0]
    assert len(shown) + decisions["repost"] + low == 7


def test_bind_short_words():
    assert bind_short_words("tea in the morning") == f"tea in{NBSP}the{NBSP}morning"


def test_balanced_wrap_keeps_line_count_and_evens_lengths():
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    from meme_pipeline.render import load_font

    font = load_font(None, 20)
    text = "one two three four five six seven eight nine ten eleven"
    greedy = wrap_greedy(text, font, 300, draw)
    balanced = wrap_balanced(text, font, 300, draw)
    assert len(balanced) == len(greedy)
    spread = lambda lines: max(map(len, lines)) - min(map(len, lines))
    assert spread(balanced) <= spread(greedy)


def test_fit_text_shrinks_for_long_text():
    short = fit_text("Hi", None, 600, 300)
    long = fit_text("word " * 80, None, 600, 300)
    assert short.font.size > long.font.size
    assert long.height <= 300


def test_render_outputs(tmp_path):
    src = tmp_path / "p.png"
    noise_image(3).save(src)
    assert caption_card(src, "When the coffee kicks in", size=400).size == (400, 400)
    assert chat_bubble("- Are you ok?\n- I am fine.", size=400).size == (400, 400)


def test_month_range():
    assert add_month(date(2024, 1, 31)) == date(2024, 2, 29)
    days = month_days(date(2024, 3, 15))
    assert days[0] == date(2024, 3, 15) and days[-1] == date(2024, 4, 14)


def test_schedule_uses_fallbacks():
    weekly = {d: ["meme", "story"] for d in range(7)}
    start = date(2024, 6, 3)
    slots = build_schedule(start, weekly, {"meme": list(range(100)), "story": [1000, 1001]}, {"story": ["meme"]})
    assert len(slots) == 2 * len(month_days(start))
    assert [s.post_id for s in slots if s.kind == "story"] == [1000, 1001]
    assert demand(start, weekly) == {"meme": 30, "story": 30}


def test_schedule_month_writes_times(tmp_path):
    conn = connect(tmp_path / "m.db")
    conn.executemany("INSERT INTO posts (target, kind, text) VALUES ('t', ?, 'x')", [("meme",)] * 10 + [("story",)] * 2)
    cfg = TargetConfig(Target("t", {}), "@chat", weekly={0: ["meme", "story"], 2: ["meme"]}, fallbacks={"story": ["meme"]})
    scheduled, shortage = schedule_month(conn, cfg, date(2024, 7, 1))
    assert scheduled == 12
    assert shortage == {"story": 3}
    first = conn.execute("SELECT publish_at FROM posts ORDER BY publish_at LIMIT 2").fetchall()
    assert [r[0] for r in first] == ["2024-07-01T09:00", "2024-07-01T21:00"]
    assert datetime.fromisoformat(first[0][0])
