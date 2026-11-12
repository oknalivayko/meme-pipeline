"""Relative virality scores.

Raw reaction counts cannot be compared across channels (a channel with 500k
subscribers beats a small one on every post) or across time (reactions grow as a
channel grows). Every post is therefore compared with the average of its own
channel in the same month:

    channel_score = reactions / mean(reactions of the channel in that month)

1.0 is an ordinary post, 3.0 is three times better than usual for that channel
at that time. `laugh_score` does the same for laughing reactions only, which
separates funny posts from merely liked ones. `global_score` compares a post
with all channels in the same month.
"""
import sqlite3
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Scores:
    channel: float
    laugh: float
    global_: float


def ratio(value: float, mean: float) -> float:
    return round(value / mean, 3) if mean > 0 else 0.0


def compute_scores(rows: list[tuple[str, str, int, int]]) -> list[Scores]:
    """rows: (source, year_month, total_reactions, laugh_reactions)."""
    per_channel = defaultdict(lambda: [0, 0, 0])
    per_month = defaultdict(lambda: [0, 0])

    for source, month, total, laugh in rows:
        c = per_channel[(source, month)]
        c[0] += total
        c[1] += laugh
        c[2] += 1
        m = per_month[month]
        m[0] += total
        m[1] += 1

    scores = []
    for source, month, total, laugh in rows:
        c_total, c_laugh, c_count = per_channel[(source, month)]
        m_total, m_count = per_month[month]
        scores.append(Scores(
            channel=ratio(total, c_total / c_count),
            laugh=ratio(laugh, c_laugh / c_count),
            global_=ratio(total, m_total / m_count),
        ))
    return scores


def rescore(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id, source, year_month, total_reactions, laugh_reactions FROM memes").fetchall()
    scores = compute_scores([(r["source"], r["year_month"], r["total_reactions"], r["laugh_reactions"]) for r in rows])
    conn.executemany(
        "UPDATE memes SET channel_score = ?, laugh_score = ?, global_score = ? WHERE id = ?",
        [(s.channel, s.laugh, s.global_, r["id"]) for s, r in zip(scores, rows)],
    )
    conn.commit()
    return len(rows)
