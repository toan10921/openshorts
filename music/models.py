"""Data contracts for Music Reader jobs and lyric artifacts."""

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class MusicJobOptions:
    language: str = "vi"
    separate_vocals: bool = False
    create_tts: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class LyricLine:
    id: str
    start: float
    end: float
    text: str
    confidence: Optional[float] = None

    def to_dict(self):
        return asdict(self)
