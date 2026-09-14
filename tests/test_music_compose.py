import shutil
import subprocess

import pytest

from music.compose import (
    media_duration,
    media_has_audio,
    media_has_video,
    render_intro_overlay,
    render_lyric_excerpt,
    render_music_excerpt_join,
    render_music_leadin,
    render_preview,
)


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg is required",
)


def _run(command):
    subprocess.run(command, check=True, capture_output=True)


@pytest.fixture()
def sample_media(tmp_path):
    video = tmp_path / "short.mp4"
    music = tmp_path / "music.wav"
    _run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x568:r=24:d=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(video),
    ])
    _run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "sine=frequency=880:duration=5:sample_rate=48000", str(music),
    ])
    return video, music


def test_render_preview_creates_requested_audio_excerpt(sample_media, tmp_path):
    _, music = sample_media
    output = tmp_path / "preview.mp3"
    render_preview(music, output, 1.0, 2.25)
    assert output.is_file()
    assert media_has_audio(output)
    assert media_duration(output) == pytest.approx(1.25, abs=0.12)


def test_render_lyric_excerpt_keeps_final_word_and_tail_padding(sample_media, tmp_path):
    _, music = sample_media
    output = tmp_path / "excerpt.wav"
    details = render_lyric_excerpt(
        music, output, match_end=4.0, source_duration=5.0,
        excerpt_seconds=3.0, tail_padding=0.15,
    )
    assert output.is_file()
    assert media_duration(output) == pytest.approx(3.0, abs=0.04)
    assert details == {
        "start": 1.15,
        "match_end": 4.0,
        "end": 4.15,
        "duration": 3.0,
        "tail_padding": 0.15,
    }


def test_render_lyric_excerpt_clamps_padding_at_end_of_song(sample_media, tmp_path):
    _, music = sample_media
    output = tmp_path / "end-excerpt.wav"
    details = render_lyric_excerpt(
        music, output, match_end=4.95, source_duration=5.0,
        excerpt_seconds=10, tail_padding=0.15,
    )
    assert output.is_file()
    assert details["start"] == 0.0
    assert details["end"] == 5.0
    assert details["tail_padding"] == pytest.approx(0.05)


def test_join_uses_same_final_word_safe_range_as_wav(sample_media, tmp_path):
    video, music = sample_media
    output = tmp_path / "joined-final-word.mp4"
    details = render_music_excerpt_join(
        video, music, output, match_end=4.0, source_duration=5.0,
        excerpt_seconds=3.0, tail_padding=0.15,
    )
    assert output.is_file()
    assert media_duration(output) == pytest.approx(6.0, abs=0.15)
    assert details["lead_start"] == 1.15
    assert details["match_end"] == 4.0
    assert details["lead_end"] == 4.15
    assert details["lead_duration"] == 3.0
    assert details["tail_padding"] == 0.15


def test_join_burns_ass_captions_on_intro(sample_media, tmp_path):
    from subtitles import AUTO_CAPTION_STYLE, generate_ass

    video, music = sample_media
    subtitle = tmp_path / "lyric-intro.ass"
    transcript = {"segments": [{"words": [
        {"word": " Xin", "start": 2.0, "end": 2.5},
        {"word": " chào", "start": 2.5, "end": 3.0},
    ]}]}
    style = AUTO_CAPTION_STYLE
    assert generate_ass(
        transcript, 1.0, 4.0, subtitle,
        max_chars=style["max_chars"], max_duration=style["max_duration"],
        alignment=style["alignment"], fontsize=style["font_size"],
        font_name=style["font_name"], font_color=style["font_color"],
        border_color=style["border_color"], border_width=style["border_width"],
        highlight_color=style["highlight_color"], effect=style["effect"],
        base_opacity=style["base_opacity"], uppercase=style["uppercase"],
    )
    output = tmp_path / "joined-captioned.mp4"
    render_music_excerpt_join(
        video, music, output, match_end=3.85, source_duration=5.0,
        excerpt_seconds=3.0, tail_padding=0.15, subtitle_path=subtitle,
    )
    assert output.is_file()
    assert media_duration(output) == pytest.approx(6.0, abs=0.15)


def test_media_stream_detection_distinguishes_video_and_audio(sample_media):
    video, music = sample_media
    assert media_has_video(video)
    assert media_has_audio(video)
    assert not media_has_video(music)


@pytest.mark.parametrize("mode", ["mix", "replace"])
def test_render_overlay_preserves_video_and_outputs_full_audio(sample_media, tmp_path, mode):
    video, music = sample_media
    output = tmp_path / f"overlay-{mode}.mp4"
    details = render_intro_overlay(video, music, output, 1.0, 2.0, mode=mode)
    assert output.is_file()
    assert media_has_audio(output)
    assert media_duration(output) == pytest.approx(3.0, abs=0.12)
    assert details == {
        "video_duration": pytest.approx(3.0, abs=0.12),
        "excerpt_duration": 1.0,
        "has_original_audio": True,
    }


@pytest.mark.parametrize("mode", ["mix", "replace"])
def test_render_overlay_handles_music_selection_longer_than_short(sample_media, tmp_path, mode):
    video, music = sample_media
    output = tmp_path / f"full-overlay-{mode}.mp4"
    details = render_intro_overlay(video, music, output, 0.5, 4.5, mode=mode)
    assert output.is_file()
    assert media_duration(output) == pytest.approx(3.0, abs=0.12)
    assert details["excerpt_duration"] == pytest.approx(3.0, abs=0.12)


def test_render_music_leadin_extends_short_and_ends_at_match(sample_media, tmp_path):
    video, music = sample_media
    output = tmp_path / "with-leadin.mp4"
    details = render_music_leadin(video, music, output, match_start=4.0, lead_seconds=2.0)
    assert output.is_file()
    assert media_has_audio(output)
    assert media_duration(output) == pytest.approx(5.0, abs=0.15)
    assert details["lead_start"] == 2.0
    assert details["lead_end"] == 4.0
    assert details["lead_duration"] == 2.0
    assert details["output_duration"] == pytest.approx(5.0, abs=0.12)


def test_render_music_leadin_clamps_to_start_of_song(sample_media, tmp_path):
    video, music = sample_media
    output = tmp_path / "short-leadin.mp4"
    details = render_music_leadin(video, music, output, match_start=1.25, lead_seconds=10)
    assert output.is_file()
    assert media_duration(output) == pytest.approx(4.25, abs=0.15)
    assert details["lead_start"] == 0.0
    assert details["lead_duration"] == 1.25
