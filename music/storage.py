"""Safe, atomic storage helpers for Music Reader artifacts."""

import json
import os
from pathlib import Path


ARTIFACT_NAMES = {
    "lyrics.json",
    "lyrics.txt",
    "lyrics.srt",
    "source.json",
    "transcript.json",
}


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path, value):
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
    )


def artifact_path(output_dir, name):
    """Resolve a public artifact name without allowing path traversal."""
    if name not in ARTIFACT_NAMES:
        raise ValueError("Unknown music artifact")
    root = Path(output_dir).resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise ValueError("Artifact escapes its job directory")
    return candidate
