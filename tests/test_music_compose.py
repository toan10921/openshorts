import shutil
import subprocess

import pytest

from music.compose import media_duration, media_has_audio, render_intro_overlay, render_preview


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
