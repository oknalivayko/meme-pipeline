"""Chooses the next meme to show to the editor.

Each target channel has its own list of donor sources with weights. Donors are
drawn from a shuffled "deck" in which a donor with weight 3 appears three
times, so heavy donors are shown more often but the order stays varied. From
the drawn donor the best not yet reviewed meme above the score threshold is
taken; if it looks like something already reviewed (perceptual hash), it is
auto-rejected as a repost and the search continues.
"""
import random
import sqlite3
from dataclasses import dataclass, field

from .imagehash import HashIndex, dhash


@dataclass
class Target:
    name: str
    donors: dict[str, int]
    score_field: str = "channel_score"
    min_score: float = 1.0


SCORE_FIELDS = {"channel_score", "laugh_score", "global_score"}


@dataclass
class Selector:
    conn: sqlite3.Connection
    target: Target
    hash_threshold: int = 12
    rng: random.Random = field(default_factory=random.Random)
    deck: list[str] = field(default_factory=list)
    index: HashIndex = field(init=False)

    def __post_init__(self):
        if self.target.score_field not in SCORE_FIELDS:
            raise ValueError(f"unknown score field {self.target.score_field}")
        self.index = HashIndex(self.hash_threshold)
        for row in self.conn.execute(
            "SELECT meme_id, image_hash FROM decisions WHERE target = ? AND image_hash IS NOT NULL",
            (self.target.name,),
        ):
            self.index.add(row["meme_id"], int(row["image_hash"], 16))

    def _refill(self) -> None:
        self.deck = [donor for donor, weight in self.target.donors.items() for _ in range(weight)]
        self.rng.shuffle(self.deck)

    def _best_from(self, donor: str) -> sqlite3.Row | None:
        return self.conn.execute(
            f"""
            SELECT m.* FROM memes m
            LEFT JOIN decisions d ON d.meme_id = m.id AND d.target = ?
            WHERE d.meme_id IS NULL AND m.source = ? AND m.photo_path IS NOT NULL
              AND m.{self.target.score_field} >= ?
            ORDER BY m.{self.target.score_field} DESC, m.total_reactions DESC
            LIMIT 1
            """,
            (self.target.name, donor, self.target.min_score),
        ).fetchone()

    def record(self, meme_id: int, decision: str, image_hash: int | None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO decisions (meme_id, target, decision, image_hash) VALUES (?, ?, ?, ?)",
            (meme_id, self.target.name, decision, f"{image_hash:x}" if image_hash is not None else None),
        )
        self.conn.commit()
        if image_hash is not None:
            self.index.add(meme_id, image_hash)

    def next_candidate(self) -> tuple[sqlite3.Row, int] | None:
        exhausted: set[str] = set()
        while len(exhausted) < len(self.target.donors):
            if not self.deck:
                self._refill()
            donor = self.deck.pop()
            if donor in exhausted:
                continue

            meme = self._best_from(donor)
            if meme is None:
                exhausted.add(donor)
                continue
            try:
                image_hash = dhash(meme["photo_path"])
            except OSError:
                self.record(meme["id"], "broken", None)
                continue
            if self.index.find(image_hash) is not None:
                self.record(meme["id"], "repost", image_hash)
                continue
            return meme, image_hash
        return None
