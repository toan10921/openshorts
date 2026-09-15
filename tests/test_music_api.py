import asyncio
import json
import os

import httpx
import pytest

app_module = pytest.importorskip("app")


def _request(method, path, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


@pytest.fixture()
def music_dirs(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "output"
    uploads.mkdir()
    outputs.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(uploads))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(app_module, "MUSIC_ENABLED", True)
    app_module.pending_uploads.clear()
    app_module.music_jobs.clear()
    scheduled = []
    monkeypatch.setattr(app_module, "_schedule_music_job", scheduled.append)
    yield uploads, outputs, scheduled
    app_module.pending_uploads.clear()
    app_module.music_jobs.clear()


def _completed_slot(uploads, filename="bai-hat.mp3"):
    upload_id = "upload-test"
    # The on-disk path has already been sanitized by POST /api/uploads; keep a
    # potentially hostile original filename in the slot to exercise the music
    # endpoint's own basename handling.
    path = uploads / f"pending_{upload_id}_payload"
    path.write_bytes(b"audio")
    app_module.pending_uploads[upload_id] = {
        "user_id": None,
        "filename": filename,
        "path": str(path),
        "created": 1,
        "bytes": 5,
        "complete": True,
    }
    return upload_id, path


def test_create_music_job_consumes_upload_and_schedules(music_dirs):
    uploads, outputs, scheduled = music_dirs
    upload_id, old_path = _completed_slot(uploads, "../bai-hat.mp3")

    response = _request("POST", "/api/music/jobs", json={"upload_id": upload_id})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["options"]["language"] == "vi"
    assert scheduled == [payload["id"]]
    assert upload_id not in app_module.pending_uploads
    assert not old_path.exists()
    record = app_module.music_jobs[payload["id"]]
    assert os.path.isfile(record["input_path"])
    assert os.path.basename(record["input_path"]) == "source_upload.mp3"
    assert os.path.isfile(outputs / payload["id"] / "music-job.json")


def test_create_music_job_uses_cross_filesystem_safe_move(music_dirs, monkeypatch):
    uploads, _, scheduled = music_dirs
    upload_id, old_path = _completed_slot(uploads)
    real_move = app_module.shutil.move
    seen = {}

    def move(source, destination):
        seen.update(source=source, destination=destination)
        return real_move(source, destination)

    monkeypatch.setattr(app_module.shutil, "move", move)
    response = _request("POST", "/api/music/jobs", json={"upload_id": upload_id})
    assert response.status_code == 200
    assert seen["source"] == str(old_path)
    assert "/output/music_" in seen["destination"]
    assert scheduled == [response.json()["id"]]


def test_music_job_rejects_unavailable_m1_features(music_dirs):
    uploads, _, scheduled = music_dirs
    upload_id, _ = _completed_slot(uploads)
    response = _request("POST", "/api/music/jobs", json={
        "upload_id": upload_id,
        "separate_vocals": True,
    })
    assert response.status_code == 400
    assert "M2" in response.text
    assert upload_id in app_module.pending_uploads
    assert not scheduled


def test_get_completed_job_adds_protected_artifact_urls(music_dirs):
    _, outputs, _ = music_dirs
    job_id = "music_" + "a" * 32
    output = outputs / job_id
    output.mkdir()
    (output / "lyrics.txt").write_text("Xin chào\n", encoding="utf-8")
    app_module.music_jobs[job_id] = {
        "status": "completed", "stage": "complete", "progress": 100,
        "source": {}, "options": {}, "error": None, "created_at": "now",
        "user_id": None, "output_dir": str(output),
        "result": {"artifacts": {"txt": "lyrics.txt"}},
    }
    response = _request("GET", f"/api/music/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["result"]["artifacts"]["txt"].endswith("/artifacts/lyrics.txt")
    artifact = _request("GET", f"/api/music/jobs/{job_id}/artifacts/lyrics.txt")
    assert artifact.status_code == 200
    assert artifact.text == "Xin chào\n"


def test_latest_music_job_restores_most_recent_record(music_dirs):
    _, outputs, _ = music_dirs
    for suffix, created in (("8", "2026-01-01T00:00:00Z"), ("9", "2026-02-01T00:00:00Z")):
        job_id = "music_" + suffix * 32
        output = outputs / job_id
        output.mkdir()
        app_module.music_jobs[job_id] = {
            "status": "completed", "stage": "complete", "created_at": created,
            "user_id": None, "output_dir": str(output), "result": {},
        }
    response = _request("GET", "/api/music/jobs/latest")
    assert response.status_code == 200
    assert response.json()["id"] == "music_" + "9" * 32


def test_artifact_endpoint_does_not_serve_internal_files(music_dirs):
    _, outputs, _ = music_dirs
    job_id = "music_" + "b" * 32
    output = outputs / job_id
    output.mkdir()
    (output / "normalized.wav").write_bytes(b"private")
    app_module.music_jobs[job_id] = {
        "status": "completed", "user_id": None, "output_dir": str(output),
        "result": {"artifacts": {}},
    }
    response = _request("GET", f"/api/music/jobs/{job_id}/artifacts/normalized.wav")
    assert response.status_code == 404


def test_recovery_keeps_results_but_marks_interrupted_job_failed(music_dirs):
    _, outputs, _ = music_dirs
    job_id = "music_" + "c" * 32
    output = outputs / job_id
    output.mkdir()
    (output / "music-job.json").write_text(
        '{"status":"running","stage":"transcribe","progress":35,"options":{}}',
        encoding="utf-8",
    )
    app_module._recover_music_jobs_from_disk()
    recovered = app_module.music_jobs[job_id]
    assert recovered["status"] == "failed"
    assert "restarted" in recovered["error"]


def test_retry_reuses_original_upload(music_dirs):
    _, outputs, scheduled = music_dirs
    job_id = "music_" + "d" * 32
    output = outputs / job_id
    output.mkdir()
    source = output / "source_upload.mp3"
    source.write_bytes(b"audio")
    app_module.music_jobs[job_id] = {
        "status": "completed", "stage": "complete", "progress": 100,
        "source": {"filename": "song.mp3"},
        "options": {"language": "vi", "separate_vocals": False, "create_tts": False},
        "result": {"line_count": 1}, "error": None, "created_at": "now",
        "user_id": None, "output_dir": str(output), "input_path": str(source),
    }
    response = _request("POST", f"/api/music/jobs/{job_id}/retry")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert scheduled == [job_id]


def _completed_music(outputs, suffix="e"):
    job_id = "music_" + suffix * 32
    output = outputs / job_id
    output.mkdir()
    source = output / "source_upload.mp3"
    source.write_bytes(b"audio")
    (output / "source.json").write_text(
        json.dumps({"duration": 120, "sha256": "abc123"}), encoding="utf-8",
    )
    app_module.music_jobs[job_id] = {
        "status": "completed", "user_id": None, "output_dir": str(output),
        "input_path": str(source), "result": {},
    }
    return job_id, output


def test_search_music_lyrics_returns_ranked_timestamps(music_dirs):
    _, outputs, _ = music_dirs
    job_id, output = _completed_music(outputs)
    (output / "transcript.json").write_text(json.dumps({
        "segments": [{"words": [
            {"word": "Xin", "start": 7.2, "end": 7.5},
            {"word": "đừng", "start": 7.5, "end": 7.9},
            {"word": "rời", "start": 7.9, "end": 8.2},
            {"word": "xa", "start": 8.2, "end": 8.5},
            {"word": "anh", "start": 8.5, "end": 8.9},
        ]}],
    }), encoding="utf-8")
    response = _request(
        "POST", f"/api/music/jobs/{job_id}/search",
        json={"query": "xin dung roi xa anh", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    best = response.json()["candidates"][0]
    assert best["start"] == 7.2
    assert best["end"] == 8.9
    assert best["score"] == 1.0


def test_preview_uses_original_music_and_bounds_selection(music_dirs, monkeypatch):
    _, outputs, _ = music_dirs
    job_id, _ = _completed_music(outputs, "f")
    seen = {}

    def render(source, output, start, end):
        seen.update(source=source, start=start, end=end)
        with open(output, "wb") as target:
            target.write(b"preview")

    monkeypatch.setattr("music.compose.render_preview", render)
    response = _request(
        "GET", f"/api/music/jobs/{job_id}/preview?start=10&end=13&padding=.25",
    )
    assert response.status_code == 200, response.text
    assert response.content == b"preview"
    assert seen["source"].endswith("source_upload.mp3")
    assert seen["start"] == 9.75
    assert seen["end"] == 13.25

    too_long = _request(
        "GET", f"/api/music/jobs/{job_id}/preview?start=1&end=40&padding=0",
    )
    assert too_long.status_code == 400


def test_export_excerpt_uses_match_end_and_preserves_tail(music_dirs, monkeypatch):
    _, outputs, _ = music_dirs
    job_id, output = _completed_music(outputs, "7")
    seen = {}

    def render(source, target, match_end, source_duration, excerpt_seconds, tail_padding):
        seen.update(
            source=source, match_end=match_end, source_duration=source_duration,
            excerpt_seconds=excerpt_seconds, tail_padding=tail_padding,
        )
        with open(target, "wb") as destination:
            destination.write(b"wav")
        return {
            "start": 53.67, "match_end": 63.52, "end": 63.67,
            "duration": 10.0, "tail_padding": 0.15,
        }

    monkeypatch.setattr("music.compose.render_lyric_excerpt", render)
    response = _request("POST", f"/api/music/jobs/{job_id}/excerpt", json={
        "match_start": 60.82,
        "match_end": 63.52,
        "query": "hạnh phúc anh xây",
        "matched_text": "Hạnh phúc anh say",
        "match_score": 0.88,
        "excerpt_seconds": 10,
        "tail_padding": 0.15,
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["audio_url"].startswith(f"/videos/{job_id}/lyric_excerpt_")
    assert (output / os.path.basename(payload["audio_url"])).read_bytes() == b"wav"
    assert seen["match_end"] == 63.52
    assert seen["excerpt_seconds"] == 10
    assert seen["tail_padding"] == 0.15
    assert payload["plan"]["excerpt"]["end"] == 63.67
    assert (output / os.path.basename(payload["plan_url"])).is_file()


def test_overlay_creates_new_video_and_reproducible_plan(music_dirs, monkeypatch):
    _, outputs, _ = music_dirs
    music_job_id, music_output = _completed_music(outputs, "1")
    (music_output / "transcript.json").write_text(json.dumps({
        "segments": [{"words": [
            {"word": " Xin", "start": 10.0, "end": 10.4},
            {"word": " chào", "start": 10.4, "end": 10.9},
            {"word": " bạn", "start": 10.9, "end": 11.4},
            {"word": " Next", "start": 13.0, "end": 13.4},
        ]}],
    }), encoding="utf-8")
    video_job_id = "video-job"
    video_output = outputs / video_job_id
    video_output.mkdir()
    video = video_output / "clip.mp4"
    video.write_bytes(b"video")
    short_job = {
        "status": "completed", "user_id": None,
        "result": {"clips": [{
            "video_url": f"/videos/{video_job_id}/clip.mp4",
            "video_title_for_youtube_short": "Clip one",
        }]},
    }
    monkeypatch.setattr(app_module, "_job_record", lambda value: short_job if value == video_job_id else None)

    def render(video_path, music_path, output_path, *args):
        assert video_path == str(video)
        assert music_path.endswith("source_upload.mp3")
        assert args[-2].endswith(".ass")
        assert os.path.isfile(args[-2])
        assert args[-1] is None
        with open(output_path, "wb") as target:
            target.write(b"rendered")
        return {"video_duration": 30, "excerpt_duration": 3, "has_original_audio": True}

    monkeypatch.setattr("music.compose.render_music_excerpt_join", render)
    response = _request("POST", "/api/music/overlay", json={
        "music_job_id": music_job_id,
        "video_job_id": video_job_id,
        "clip_index": 0,
        "start": 10,
        "end": 13,
        "query": "xin đừng rời xa anh",
        "matched_text": "Xin đừng rời xa anh",
        "match_score": 0.95,
        "lead_seconds": 10,
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["video_url"].startswith(f"/videos/{video_job_id}/music_leadin_")
    assert (video_output / os.path.basename(payload["video_url"])).read_bytes() == b"rendered"
    plan = payload["plan"]
    assert plan["music"]["start"] == 10
    assert plan["video"]["source_file"] == "clip.mp4"
    assert plan["compose"]["placement"] == "prepend"
    assert plan["compose"]["lead_seconds_requested"] == 10
    assert plan["compose"]["tail_padding"] == 0.15
    assert plan["captions"]["enabled"] is True
    assert plan["captions"]["style"] == "openshorts_karaoke"
    assert plan["captions"]["words"]
    assert all(word["text"] != "Next" for word in plan["captions"]["words"])
    assert (video_output / os.path.basename(plan["captions"]["ass_url"])).is_file()
    assert (video_output / os.path.basename(plan["captions"]["srt_url"])).is_file()
    assert plan["hook_visual"]["used"] == "hold_frame"
    assert "PEXELS_API_KEY" in plan["hook_visual"]["fallback_reason"]
    assert (video_output / os.path.basename(payload["plan_url"])).is_file()


def test_overlay_accepts_manually_uploaded_video(music_dirs, monkeypatch):
    uploads, outputs, _ = music_dirs
    music_job_id, music_output = _completed_music(outputs, "2")
    upload_id, upload_path = _completed_slot(uploads, "outside-video.mov")
    monkeypatch.setattr("music.compose.media_has_video", lambda path: path == str(upload_path))

    def render(video_path, music_path, output_path, *args):
        assert os.path.basename(video_path).startswith("external_video_")
        assert video_path.endswith(".mov")
        assert music_path.endswith("source_upload.mp3")
        with open(output_path, "wb") as target:
            target.write(b"external-render")
        return {"video_duration": 20, "lead_duration": 10, "output_duration": 30}

    monkeypatch.setattr("music.compose.render_music_excerpt_join", render)
    response = _request("POST", "/api/music/overlay", json={
        "music_job_id": music_job_id,
        "video_source": "upload",
        "video_upload_id": upload_id,
        "video_acknowledged": True,
        "start": 60,
        "end": 63,
        "query": "câu đầu video",
        "matched_text": "Câu đầu video",
        "lead_seconds": 10,
        "lyric_captions": False,
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["video_url"].startswith(f"/videos/{music_job_id}/music_leadin_")
    assert payload["plan"]["video"]["source"] == "upload"
    assert payload["plan"]["video"]["original_filename"] == "outside-video.mov"
    assert upload_id not in app_module.pending_uploads
    assert not upload_path.exists()
    assert list(music_output.glob("external_video_*.mov"))
    assert (music_output / os.path.basename(payload["video_url"])).read_bytes() == b"external-render"


def test_manual_video_requires_rights_confirmation(music_dirs):
    uploads, outputs, _ = music_dirs
    music_job_id, _ = _completed_music(outputs, "3")
    upload_id, _ = _completed_slot(uploads, "outside-video.mp4")
    response = _request("POST", "/api/music/overlay", json={
        "music_job_id": music_job_id,
        "video_source": "upload",
        "video_upload_id": upload_id,
        "video_acknowledged": False,
        "start": 60,
        "end": 63,
    })
    assert response.status_code == 400
    assert "Confirm" in response.text
    assert upload_id in app_module.pending_uploads
