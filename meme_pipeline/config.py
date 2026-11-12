import json
from dataclasses import dataclass, field
from pathlib import Path

from .selection import Target


@dataclass
class TargetConfig:
    target: Target
    chat_id: str
    weekly: dict[int, list[str]]
    fallbacks: dict[str, list[str]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.target.name


def load_targets(path: str | Path) -> dict[str, TargetConfig]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    targets = {}
    for t in raw["targets"]:
        targets[t["name"]] = TargetConfig(
            target=Target(
                name=t["name"],
                donors=t["donors"],
                score_field=t.get("score_field", "channel_score"),
                min_score=t.get("min_score", 1.0),
            ),
            chat_id=t.get("chat_id", ""),
            weekly={int(day): kinds for day, kinds in t["weekly"].items()},
            fallbacks=t.get("fallbacks", {}),
        )
    return targets
