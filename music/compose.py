"""FFmpeg preview and audio-overlay operations for Music Reader."""

import json
import subprocess


class MusicComposeError(RuntimeError):
    pass


def media_has_audio(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return bool(result.stdout.strip())


def media_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return float((json.loads(result.stdout).get("format") or {}).get("duration") or 0)


def render_preview(source, output, start, end, fade=0.08):
    duration = end - start
    fade = max(0.0, min(float(fade), duration / 3))
    fade_out = max(0.0, duration - fade)
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}", "-i", str(source), "-vn",
        "-af", f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={fade_out:.3f}:d={fade:.3f}",
        "-c:a", "libmp3lame", "-q:a", "4", str(output),
    ]
    _run(command, "Không thể tạo audio preview")
    return str(output)


def render_intro_overlay(video, music, output, start, end, mode="mix",
                         music_volume=0.9, original_volume=0.2, fade=0.08):
    clip_duration = media_duration(video)
    excerpt_duration = min(end - start, clip_duration)
    if excerpt_duration <= 0:
        raise MusicComposeError("Khoảng nhạc hoặc video không hợp lệ")
    fade = max(0.0, min(float(fade), excerpt_duration / 3))
    fade_out = max(0.0, excerpt_duration - fade)
    audio_format = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    music_chain = (
        f"[1:a]{audio_format},volume={music_volume:.3f},"
        f"afade=t=in:st=0:d={fade:.3f},"
        f"afade=t=out:st={fade_out:.3f}:d={fade:.3f}[music]"
    )

    has_audio = media_has_audio(video)
    covers_full_video = excerpt_duration >= clip_duration - 0.01
    if has_audio and mode == "replace" and covers_full_video:
        graph = f"{music_chain};[music]apad=whole_dur={clip_duration:.3f}[outa]"
    elif has_audio and mode == "replace":
        graph = (
            f"{music_chain};"
            f"[0:a]{audio_format},atrim=start={excerpt_duration:.3f},"
            "asetpts=PTS-STARTPTS[rest];"
            "[music][rest]concat=n=2:v=0:a=1[outa]"
        )
    elif has_audio and covers_full_video:
        graph = (
            f"{music_chain};"
            f"[0:a]{audio_format},atrim=0:{excerpt_duration:.3f},"
            f"asetpts=PTS-STARTPTS,volume={original_volume:.3f}[head];"
            "[head][music]amix=inputs=2:duration=first:normalize=0[outa]"
        )
    elif has_audio:
        graph = (
            f"{music_chain};"
            f"[0:a]{audio_format},asplit=2[headsrc][restsrc];"
            f"[headsrc]atrim=0:{excerpt_duration:.3f},asetpts=PTS-STARTPTS,"
            f"volume={original_volume:.3f}[head];"
            f"[restsrc]atrim=start={excerpt_duration:.3f},asetpts=PTS-STARTPTS[rest];"
            "[head][music]amix=inputs=2:duration=first:normalize=0[mixed];"
            "[mixed][rest]concat=n=2:v=0:a=1[outa]"
        )
    else:
        graph = f"{music_chain};[music]apad=whole_dur={clip_duration:.3f}[outa]"

    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-ss", f"{start:.3f}", "-t", f"{excerpt_duration:.3f}", "-i", str(music),
        "-filter_complex", graph, "-map", "0:v:0", "-map", "[outa]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{clip_duration:.3f}",
        "-movflags", "+faststart", str(output),
    ]
    _run(command, "Không thể ghép nhạc vào Short")
    return {
        "video_duration": round(clip_duration, 3),
        "excerpt_duration": round(excerpt_duration, 3),
        "has_original_audio": has_audio,
    }


def _run(command, message):
    try:
        subprocess.run(
            command, check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        raise MusicComposeError(f"{message}: FFmpeg hết thời gian") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail = exc.stderr.decode("utf-8", errors="replace")[-500:]
        raise MusicComposeError(f"{message}{': ' + detail if detail else ''}") from exc
