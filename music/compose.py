"""FFmpeg preview and audio-overlay operations for Music Reader."""

import json
import os
import subprocess

from ffmpeg_utils import escape_filter_value


class MusicComposeError(RuntimeError):
    pass


def _lyric_excerpt_bounds(match_end, source_duration, excerpt_seconds, tail_padding):
    protected_end = min(float(source_duration), float(match_end) + float(tail_padding))
    excerpt_start = max(0.0, protected_end - float(excerpt_seconds))
    return excerpt_start, protected_end, protected_end - excerpt_start


def media_has_audio(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return bool(result.stdout.strip())


def media_has_video(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
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


def media_video_size(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    stream = (json.loads(result.stdout).get("streams") or [{}])[0]
    return int(stream.get("width") or 0), int(stream.get("height") or 0)


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


def render_lyric_excerpt(source, output, match_end, source_duration,
                         excerpt_seconds=10.0, tail_padding=0.15):
    """Export an edit-friendly WAV ending just after the matched final word."""
    excerpt_start, protected_end, duration = _lyric_excerpt_bounds(
        match_end, source_duration, excerpt_seconds, tail_padding)
    if duration <= 0:
        raise MusicComposeError("Khoảng nhạc cần xuất không hợp lệ")
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{excerpt_start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(source), "-vn",
        "-af", "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo",
        "-c:a", "pcm_s16le", str(output),
    ]
    _run(command, "Không thể xuất đoạn nhạc")
    return {
        "start": round(excerpt_start, 3),
        "match_end": round(float(match_end), 3),
        "end": round(protected_end, 3),
        "duration": round(duration, 3),
        "tail_padding": round(protected_end - float(match_end), 3),
    }


def render_music_excerpt_join(video, music, output, match_end, source_duration,
                              excerpt_seconds=10.0, tail_padding=0.15,
                              music_volume=0.9, fade=0.08, subtitle_path=None,
                              intro_visual_path=None):
    """Prepend the same final-word-safe excerpt exported by the WAV action."""
    video_duration = media_duration(video)
    excerpt_start, protected_end, intro_duration = _lyric_excerpt_bounds(
        match_end, source_duration, excerpt_seconds, tail_padding)
    if video_duration <= 0 or intro_duration <= 0:
        raise MusicComposeError("Khoảng nhạc hoặc video không hợp lệ")
    video_width, video_height = media_video_size(video)
    if video_width <= 0 or video_height <= 0:
        raise MusicComposeError("Không đọc được kích thước video")

    fade = max(0.0, min(float(fade), intro_duration / 3))
    audio_format = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    video_format = "fps=30,format=yuv420p,settb=AVTB"
    caption_filter = ""
    if subtitle_path:
        safe_subtitle = escape_filter_value(str(subtitle_path))
        fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
        safe_fonts = escape_filter_value(fonts_dir)
        caption_filter = f",ass=filename='{safe_subtitle}':fontsdir='{safe_fonts}'"
    if intro_visual_path:
        intro_video = (
            f"[2:v]trim=duration={intro_duration:.3f},setpts=PTS-STARTPTS,"
            f"scale={video_width}:{video_height}:force_original_aspect_ratio=increase,"
            f"crop={video_width}:{video_height},setsar=1,{video_format}"
            f"{caption_filter}[introv]"
        )
    else:
        intro_video = (
            f"[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,{video_format},"
            f"tpad=stop_mode=clone:stop_duration={intro_duration:.3f},"
            f"trim=duration={intro_duration:.3f},setpts=PTS-STARTPTS,setsar=1"
            f"{caption_filter}[introv]"
        )
    main_video = f"[0:v]setpts=PTS-STARTPTS,{video_format},setsar=1[mainv]"
    # Do not fade the end of the music: that is exactly where the protected
    # final word lives. A tiny fade-in only prevents a pop at the excerpt start.
    intro_audio = (
        f"[1:a]{audio_format},atrim=duration={intro_duration:.3f},"
        f"asetpts=PTS-STARTPTS,volume={music_volume:.3f},"
        f"afade=t=in:st=0:d={fade:.3f}[introa]"
    )
    has_audio = media_has_audio(video)
    if has_audio:
        main_audio = f"[0:a]{audio_format},asetpts=PTS-STARTPTS[maina]"
    else:
        main_audio = (
            f"anullsrc=r=48000:cl=stereo,atrim=duration={video_duration:.3f},"
            "asetpts=PTS-STARTPTS[maina]"
        )
    graph = (
        f"{intro_video};{main_video};{intro_audio};{main_audio};"
        "[introv][mainv]concat=n=2:v=1:a=0[outv];"
        "[introa][maina]concat=n=2:v=0:a=1[outa]"
    )
    output_duration = intro_duration + video_duration
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-ss", f"{excerpt_start:.3f}", "-t", f"{intro_duration:.3f}",
        "-i", str(music),
    ]
    if intro_visual_path:
        command.extend(["-stream_loop", "-1", "-i", str(intro_visual_path)])
    command.extend([
        "-filter_complex", graph,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{output_duration:.3f}",
        "-movflags", "+faststart", str(output),
    ])
    _run(command, "Không thể nối đoạn nhạc vào video")
    return {
        "video_duration": round(video_duration, 3),
        "lead_start": round(excerpt_start, 3),
        "match_end": round(float(match_end), 3),
        "lead_end": round(protected_end, 3),
        "lead_duration": round(intro_duration, 3),
        "tail_padding": round(protected_end - float(match_end), 3),
        "output_duration": round(output_duration, 3),
        "has_original_audio": has_audio,
        "intro_visual": "stock" if intro_visual_path else "hold_frame",
    }


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


def render_music_leadin(video, music, output, match_start, lead_seconds=10.0,
                        music_volume=0.9, fade=0.08):
    """Prepend music ending at ``match_start`` to a Short.

    The intro holds the Short's first frame while audio plays from immediately
    before the matched lyric. The original Short then starts at t=lead_duration,
    so the matched first word is heard only once from the Short itself.
    """
    video_duration = media_duration(video)
    lead_start = max(0.0, float(match_start) - float(lead_seconds))
    lead_duration = float(match_start) - lead_start
    if video_duration <= 0 or lead_duration <= 0:
        raise MusicComposeError("Không đủ nhạc trước câu khớp để tạo lead-in")

    fade = max(0.0, min(float(fade), lead_duration / 3))
    fade_out = max(0.0, lead_duration - fade)
    audio_format = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    video_format = "fps=30,format=yuv420p,settb=AVTB"
    intro_video = (
        f"[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,{video_format},"
        f"tpad=stop_mode=clone:stop_duration={lead_duration:.3f},"
        f"trim=duration={lead_duration:.3f},setpts=PTS-STARTPTS[introv]"
    )
    main_video = f"[0:v]setpts=PTS-STARTPTS,{video_format}[mainv]"
    intro_audio = (
        f"[1:a]{audio_format},atrim=duration={lead_duration:.3f},"
        f"asetpts=PTS-STARTPTS,volume={music_volume:.3f},"
        f"afade=t=in:st=0:d={fade:.3f},"
        f"afade=t=out:st={fade_out:.3f}:d={fade:.3f}[introa]"
    )

    has_audio = media_has_audio(video)
    if has_audio:
        main_audio = (
            f"[0:a]{audio_format},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade:.3f}[maina]"
        )
    else:
        main_audio = (
            f"anullsrc=r=48000:cl=stereo,atrim=duration={video_duration:.3f},"
            "asetpts=PTS-STARTPTS[maina]"
        )
    graph = (
        f"{intro_video};{main_video};{intro_audio};{main_audio};"
        "[introv][mainv]concat=n=2:v=1:a=0[outv];"
        "[introa][maina]concat=n=2:v=0:a=1[outa]"
    )
    output_duration = lead_duration + video_duration
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-ss", f"{lead_start:.3f}", "-t", f"{lead_duration:.3f}",
        "-i", str(music), "-filter_complex", graph,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{output_duration:.3f}",
        "-movflags", "+faststart", str(output),
    ]
    _run(command, "Không thể thêm đoạn nhạc dẫn vào Short")
    return {
        "video_duration": round(video_duration, 3),
        "lead_start": round(lead_start, 3),
        "lead_end": round(float(match_start), 3),
        "lead_duration": round(lead_duration, 3),
        "output_duration": round(output_duration, 3),
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
