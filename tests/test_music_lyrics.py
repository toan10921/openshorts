import json

import pytest

from music.lyrics import _srt_time, lyric_manifest, render_srt, render_txt, transcript_to_lines
from music.storage import artifact_path


def _transcript():
    return {
        "text": " Xin chào   Việt Nam ",
        "language": "vi",
        "segments": [
            {"start": 0.42, "end": 2.15, "text": "  Xin chào  ", "words": []},
            {"start": 2.25, "end": 4.8, "text": "Việt   Nam", "words": []},
            {"start": 5, "end": 5, "text": "invalid", "words": []},
        ],
    }


def test_transcript_to_lines_normalizes_and_validates_segments():
    lines = transcript_to_lines(_transcript())
    assert [line.id for line in lines] == ["l0001", "l0002"]
    assert [line.text for line in lines] == ["Xin chào", "Việt Nam"]
    assert lines[0].start == pytest.approx(0.42)
    assert lines[1].end == pytest.approx(4.8)


def test_exports_are_utf8_friendly_and_valid_srt():
    lines = transcript_to_lines(_transcript())
    assert render_txt(lines) == "Xin chào\nViệt Nam\n"
    rendered = render_srt(lines)
    assert "00:00:00,420 --> 00:00:02,150" in rendered
    assert "\n\n2\n00:00:02,250" in rendered


def test_srt_time_supports_more_than_one_hour_and_rounding():
    assert _srt_time(3661.9996) == "01:01:02,000"


def test_lyric_manifest_is_json_serializable():
    value = lyric_manifest(_transcript(), transcript_to_lines(_transcript()))
    assert value["language"] == "vi"
    assert value["source"] == "asr"
    assert value["edited_at"] is None
    json.dumps(value, ensure_ascii=False)


def test_artifact_path_rejects_unknown_and_traversal(tmp_path):
    assert artifact_path(tmp_path, "lyrics.srt") == tmp_path / "lyrics.srt"
    with pytest.raises(ValueError):
        artifact_path(tmp_path, "../source_upload.mp3")
    with pytest.raises(ValueError):
        artifact_path(tmp_path, "normalized.wav")
