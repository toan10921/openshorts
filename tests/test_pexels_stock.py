import hashlib
import json
import time

import pytest

from stock_media import pexels


def test_choose_video_prefers_sufficient_portrait_asset():
    videos = [
        {"id": 1, "duration": 5, "video_files": [
            {"id": 11, "file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://videos.pexels.com/a.mp4"},
        ]},
        {"id": 2, "duration": 20, "video_files": [
            {"id": 22, "file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://videos.pexels.com/b.mp4"},
        ]},
    ]
    video, source = pexels._choose_video(videos, minimum_duration=10)
    assert video["id"] == 2
    assert source["id"] == 22


def test_rejects_non_pexels_download_host():
    with pytest.raises(pexels.PexelsError, match="unexpected"):
        pexels._safe_download_url("https://example.com/video.mp4")


def test_cached_query_works_without_api_key(tmp_path):
    query = "city timelapse"
    duration = 10.0
    key = hashlib.sha256(f"{query}:{duration:.2f}".encode()).hexdigest()[:20]
    video = tmp_path / "pexels_cached.mp4"
    video.write_bytes(b"cached-video")
    (tmp_path / f"query_{key}.json").write_text(json.dumps({
        "cache_file": video.name,
        "cached_at": time.time(),
        "provider": "pexels",
        "page_url": "https://www.pexels.com/video/1/",
    }), encoding="utf-8")
    path, metadata = pexels.get_pexels_timelapse(
        None, query, duration, tmp_path, ttl_days=7,
    )
    assert path == str(video)
    assert metadata["cached"] is True


def test_search_download_and_query_cache(monkeypatch, tmp_path):
    calls = {"search": 0, "download": 0}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"videos": [{
                "id": 42, "duration": 15,
                "url": "https://www.pexels.com/video/42/",
                "user": {"name": "Creator", "url": "https://www.pexels.com/@creator"},
                "video_files": [{
                    "id": 7, "file_type": "video/mp4", "width": 1080,
                    "height": 1920, "link": "https://videos.pexels.com/video.mp4",
                }],
            }]}

    class Download(Response):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def iter_bytes(self, _size):
            yield b"video-bytes"

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, url, headers, params):
            calls["search"] += 1
            assert url == pexels.PEXELS_SEARCH_URL
            assert headers["Authorization"] == "key"
            assert params["orientation"] == "portrait"
            return Response()

        def stream(self, method, url):
            calls["download"] += 1
            assert method == "GET"
            assert url.startswith("https://videos.pexels.com/")
            return Download()

    monkeypatch.setattr(pexels.httpx, "Client", Client)
    path, metadata = pexels.get_pexels_timelapse(
        "key", "city timelapse", 10, tmp_path,
    )
    assert open(path, "rb").read() == b"video-bytes"
    assert metadata["author"] == "Creator"
    assert calls == {"search": 1, "download": 1}

    # Query index avoids both another API request and another download.
    path_again, cached = pexels.get_pexels_timelapse(
        None, "city timelapse", 10, tmp_path,
    )
    assert path_again == path
    assert cached["cached"] is True
    assert calls == {"search": 1, "download": 1}

