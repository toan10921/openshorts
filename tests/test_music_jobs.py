import json
from pathlib import Path

from music.jobs import MUSIC_WHISPER_OPTIONS, MusicJobOptions, process_music_job, transcript_coverage


def test_process_music_job_writes_m1_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "song.mp3"
    source.write_bytes(b"fake audio")
    output = tmp_path / "result"

    monkeypatch.setattr("music.jobs.probe_media", lambda path: {
        "duration": 12.5,
        "format": "mp3",
        "size": source.stat().st_size,
        "audio_streams": [{"codec_type": "audio", "codec_name": "mp3"}],
    })
    monkeypatch.setattr("music.jobs.sha256_file", lambda path: "abc123")

    def fake_normalize(input_path, output_path):
        Path(output_path).write_bytes(b"wav")
        return str(output_path)

    monkeypatch.setattr("music.jobs.normalize_audio", fake_normalize)
    transcript = {
        "text": "Xin chào Việt Nam",
        "language": "vi",
        "segments": [
            {"start": 0.1, "end": 1.5, "text": "Xin chào", "words": []},
            {"start": 1.6, "end": 3.0, "text": "Việt Nam", "words": []},
        ],
    }
    seen = {}

    def fake_transcribe(path, language=None, whisper_options=None):
        seen.update(path=path, language=language, whisper_options=whisper_options)
        return transcript

    monkeypatch.setattr("transcribe_backends.transcribe_media", fake_transcribe)
    stages = []
    result = process_music_job(
        source, output, MusicJobOptions(), lambda stage, percent: stages.append((stage, percent)))

    assert seen["language"] == "vi"
    assert seen["whisper_options"] == MUSIC_WHISPER_OPTIONS
    assert seen["whisper_options"]["vad_filter"] is False
    assert seen["path"].endswith("normalized.wav")
    assert result["line_count"] == 2
    assert stages[0] == ("validate", 5)
    assert stages[-1] == ("complete", 100)
    assert (output / "lyrics.txt").read_text(encoding="utf-8") == "Xin chào\nViệt Nam\n"
    assert "00:00:00,100" in (output / "lyrics.srt").read_text(encoding="utf-8")
    assert json.loads((output / "lyrics.json").read_text())["version"] == 1
    assert json.loads((output / "source.json").read_text())["sha256"] == "abc123"


def test_transcript_coverage_merges_overlapping_segments():
    transcript = {"segments": [
        {"start": 0, "end": 4},
        {"start": 3, "end": 6},
        {"start": 9, "end": 11},
    ]}
    assert transcript_coverage(transcript, 10) == 0.7


def test_m1_rejects_future_options(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="M2"):
        process_music_job("x", tmp_path, MusicJobOptions(separate_vocals=True))
    with pytest.raises(ValueError, match="M3"):
        process_music_job("x", tmp_path, MusicJobOptions(create_tts=True))
