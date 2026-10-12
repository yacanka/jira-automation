"""Versioned metadata snapshots preserve API and UI observations separately."""

import json
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Observation:
    issue_type: str
    screen: str
    field: str
    source: str
    name: str = ""
    schema: dict = dc_field(default_factory=dict)
    required: bool | None = None
    visible: bool | None = None
    editable: bool | None = None
    options: list = dc_field(default_factory=list)
    locator: str | None = None
    issue: str | None = None
    status: str | None = None
    transition: str | None = None
    observed_at: str = dc_field(default_factory=timestamp)


@dataclass
class Catalog:
    project: str
    user: str
    observations: list[Observation] = dc_field(default_factory=list)
    transitions: list[dict] = dc_field(default_factory=list)
    issue_types: list[dict] = dc_field(default_factory=list)
    gaps: list[dict] = dc_field(default_factory=list)
    created_at: str = dc_field(default_factory=timestamp)
    version: int = 1

    def add(self, observation: Observation) -> None:
        self.observations.append(observation)

    def query(self, **filters: Any) -> list[Observation]:
        return [
            item
            for item in self.observations
            if all(
                value is None or getattr(item, key) == str(value) for key, value in filters.items()
            )
        ]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != 1:
                raise ConfigurationError("Unsupported catalog version")
            data["observations"] = [Observation(**item) for item in data["observations"]]
            return cls(**data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ConfigurationError("Invalid catalog JSON") from exc
