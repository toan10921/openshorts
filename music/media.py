"""Media validation and normalization for the local music pipeline."""

import hashlib
import json
import subprocess
from pathlib import Path


class InvalidMusicMedia(ValueError):
    pass


def probe_media(path, timeout=60):
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration,format_name,size:stream=index,codec_type,codec_name",
                "-of", "json", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise InvalidMusicMedia("Không thể đọc tệp media bằng ffprobe") from exc

    streams = payload.get("streams") or []
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise InvalidMusicMedia("Tệp không có audio track")
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise InvalidMusicMedia("Không xác định được thời lượng audio")
    return {
        "duration": duration,
        "format": (payload.get("format") or {}).get("format_name"),
        "size": int((payload.get("format") or {}).get("size") or 0),
        "audio_streams": [s for s in streams if s.get("codec_type") == "audio"],
    }


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_audio(input_path, output_path, timeout=1800):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(input_path),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidMusicMedia("FFmpeg hết thời gian khi chuẩn hóa audio") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InvalidMusicMedia("FFmpeg không thể chuẩn hóa audio") from exc
    return str(output_path)
