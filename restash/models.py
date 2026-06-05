from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SceneData:
    id: str
    title: str
    play_history: list[datetime]
    o_history: list[datetime]
    play_count: int
    o_counter: int
    play_duration: float
    resume_time: float | None
    last_played_at: datetime | None
    file_duration: float | None
    height: int | None
    marker_count: int
    organized: bool
    date: datetime | None
    created_at: datetime
    rating100: int | None
    tag_ids: list[str]
    performer_ids: list[str]
    studio_id: str | None
    custom_fields: dict
    has_file: bool


@dataclass
class PerformerData:
    id: str
    name: str
    favorite: bool
    rating100: int | None
    o_counter: int
    scene_count: int
    tag_ids: list[str]
    created_at: datetime
    custom_fields: dict


@dataclass
class SceneScore:
    id: str
    raw: float
    restash_score: int
    percentile: float
    n_events: int
    wildcard: bool
    components: dict = field(default_factory=dict)


@dataclass
class PerformerScore:
    id: str
    raw: float
    restash_score: int
    percentile: float
    components: dict = field(default_factory=dict)
