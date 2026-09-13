"""Convert the repository transcript contract into editable lyric artifacts."""

from .models import LyricLine


def transcript_to_lines(transcript):
    lines = []
    for segment in transcript.get("segments") or []:
        text = " ".join(str(segment.get("text") or "").split())
        if not text:
            continue
        try:
            start = max(0.0, float(segment.get("start")))
            end = float(segment.get("end"))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        lines.append(LyricLine(
            id=f"l{len(lines) + 1:04d}",
            start=round(start, 3),
            end=round(end, 3),
            text=text,
        ))
    return lines


def lyric_manifest(transcript, lines):
    return {
        "version": 1,
        "language": transcript.get("language") or "vi",
        "transcript": " ".join(str(transcript.get("text") or "").split()),
        "lines": [line.to_dict() for line in lines],
        "source": "asr",
        "edited_at": None,
    }


def render_txt(lines):
    text = "\n".join(line.text for line in lines)
    return text + ("\n" if text else "")


def _srt_time(seconds):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def render_srt(lines):
    blocks = []
    for index, line in enumerate(lines, 1):
        blocks.append(
            f"{index}\n{_srt_time(line.start)} --> {_srt_time(line.end)}\n{line.text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
