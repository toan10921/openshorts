"""Synchronous orchestration for one Music Reader job."""

import os
from pathlib import Path

from .lyrics import lyric_manifest, render_srt, render_txt, transcript_to_lines
from .media import normalize_audio, probe_media, sha256_file
from .models import MusicJobOptions
from .storage import atomic_write_json, atomic_write_text


# Silero VAD is tuned for spoken voice and classified almost all vocals in a
# real 43-minute Vietnamese remix as non-speech (only 4.64 seconds survived).
# Music Reader therefore decodes the full waveform. The conservative decoding
# settings limit repetition; vocal separation remains the stronger M2 path.
MUSIC_WHISPER_OPTIONS = {
    "vad_filter": False,
    "temperature": 0.0,
    "no_speech_threshold": None,
    "condition_on_previous_text": False,
    "hallucination_silence_threshold": 2.0,
    "initial_prompt": "Lời bài hát tiếng Việt, viết đúng dấu và đúng chính tả.",
}


def transcript_coverage(transcript, duration):
    """Fraction of media covered by non-overlapping ASR segment spans."""
    spans = []
    for segment in transcript.get("segments") or []:
        try:
            start = max(0.0, float(segment.get("start")))
            end = min(float(duration), float(segment.get("end")))
        except (TypeError, ValueError):
            continue
        if end > start:
            spans.append((start, end))
    if not spans or duration <= 0:
        return 0.0
    spans.sort()
    covered = 0.0
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            covered += current_end - current_start
            current_start, current_end = start, end
    covered += current_end - current_start
    return min(1.0, covered / float(duration))


def process_music_job(input_path, output_dir, options=None, on_progress=None):
    options = options or MusicJobOptions()
    if options.language != "vi":
        raise ValueError("M1 chỉ hỗ trợ nhận dạng tiếng Việt (vi)")
    if options.separate_vocals:
        raise ValueError("Tách vocal sẽ được hỗ trợ ở M2")
    if options.create_tts:
        raise ValueError("Đọc lời bằng TTS sẽ được hỗ trợ ở M3")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    def progress(stage, percent):
        if on_progress:
            on_progress(stage, percent)

    progress("validate", 5)
    probe = probe_media(input_path)
    max_duration = int(os.environ.get("MUSIC_MAX_DURATION_SECONDS", "3600"))
    if max_duration > 0 and probe["duration"] > max_duration:
        raise ValueError(
            f"Audio dài {probe['duration']:.0f}s, vượt giới hạn {max_duration}s"
        )
    source_metadata = {
        "sha256": sha256_file(input_path),
        "duration": round(probe["duration"], 3),
        "format": probe["format"],
        "size": probe["size"],
        "audio_streams": probe["audio_streams"],
    }
    atomic_write_json(output / "source.json", source_metadata)

    progress("normalize", 20)
    normalized = output / "normalized.wav"
    normalize_audio(input_path, normalized)

    progress("transcribe", 35)
    from transcribe_backends import transcribe_media
    transcript = transcribe_media(
        str(normalized),
        language=options.language,
        whisper_options=MUSIC_WHISPER_OPTIONS,
    )
    atomic_write_json(output / "transcript.json", transcript)

    progress("export", 85)
    lines = transcript_to_lines(transcript)
    manifest = lyric_manifest(transcript, lines)
    atomic_write_json(output / "lyrics.json", manifest)
    atomic_write_text(output / "lyrics.txt", render_txt(lines))
    atomic_write_text(output / "lyrics.srt", render_srt(lines))

    progress("complete", 100)
    coverage = transcript_coverage(transcript, source_metadata["duration"])
    warnings = []
    if coverage < 0.05:
        warnings.append(
            "Whisper recognized less than 5% of this track. Vocal separation is recommended."
        )
    return {
        "language": manifest["language"],
        "duration": source_metadata["duration"],
        "line_count": len(lines),
        "transcript_coverage": round(coverage, 4),
        "warnings": warnings,
        "artifacts": {
            "json": "lyrics.json",
            "txt": "lyrics.txt",
            "srt": "lyrics.srt",
            "transcript": "transcript.json",
            "source": "source.json",
        },
    }
