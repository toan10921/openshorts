"""Small, bounded Pexels video search/download adapter."""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
_CACHE_LOCK = threading.Lock()


class PexelsError(RuntimeError):
    pass


def _choose_video(videos, minimum_duration):
    choices = []
    for order, video in enumerate(videos or []):
        duration = float(video.get("duration") or 0)
        for source in video.get("video_files") or []:
            if source.get("file_type") != "video/mp4" or not source.get("link"):
                continue
            width = int(source.get("width") or 0)
            height = int(source.get("height") or 0)
            if width <= 0 or height <= 0:
                continue
            portrait_penalty = abs((width / height) - (9 / 16))
            duration_penalty = 0 if duration >= minimum_duration else minimum_duration - duration
            resolution_penalty = abs(height - 1920) / 1920
            choices.append((
                duration_penalty, portrait_penalty, resolution_penalty, order,
                video, source,
            ))
    if not choices:
        raise PexelsError("Pexels returned no usable MP4 video")
    choices.sort(key=lambda item: item[:4])
    return choices[0][4], choices[0][5]


def _safe_download_url(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "pexels.com" or host.endswith(".pexels.com")):
        raise PexelsError("Pexels returned an unexpected download URL")
    return url


def _prune_cache(cache_dir, ttl_days, max_gb):
    now = time.time()
    ttl_seconds = max(1, float(ttl_days)) * 86400
    files = []
    for path in Path(cache_dir).glob("*.mp4"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime > ttl_seconds:
            try:
                path.unlink()
                path.with_suffix(".json").unlink(missing_ok=True)
            except OSError:
                pass
            continue
        files.append((stat.st_mtime, stat.st_size, path))
    limit = max(0.1, float(max_gb)) * 1024 ** 3
    used = sum(size for _, size, _ in files)
    for _, size, path in sorted(files):
        if used <= limit:
            break
        try:
            path.unlink()
            path.with_suffix(".json").unlink(missing_ok=True)
            used -= size
        except OSError:
            pass


def get_pexels_timelapse(api_key, query, minimum_duration, cache_dir,
                         ttl_days=7, max_gb=5, timeout=30):
    query = " ".join(str(query or "city timelapse").split())[:120]
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    query_key = hashlib.sha256(f"{query}:{float(minimum_duration):.2f}".encode()).hexdigest()[:20]
    query_index = cache_dir / f"query_{query_key}.json"
    try:
        indexed = json.loads(query_index.read_text(encoding="utf-8"))
        indexed_path = cache_dir / os.path.basename(indexed["cache_file"])
        fresh = time.time() - float(indexed["cached_at"]) <= max(1, float(ttl_days)) * 86400
        if fresh and indexed_path.is_file() and indexed_path.stat().st_size > 0:
            os.utime(indexed_path, None)
            indexed["cached"] = True
            return str(indexed_path), indexed
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    if not str(api_key or "").strip():
        raise PexelsError("PEXELS_API_KEY is not configured")

    with httpx.Client(timeout=float(timeout), follow_redirects=True) as client:
        response = client.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": str(api_key).strip()},
            params={
                "query": query,
                "orientation": "portrait",
                "size": "medium",
                "locale": "en-US",
                "per_page": 15,
            },
        )
        if response.status_code == 429:
            raise PexelsError("Pexels rate limit reached")
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PexelsError(f"Pexels search failed ({response.status_code})") from exc

        video, source = _choose_video(payload.get("videos"), float(minimum_duration))
        download_url = _safe_download_url(source.get("link"))
        cache_key = hashlib.sha256(
            f"{video.get('id')}:{source.get('id')}:{download_url}".encode()
        ).hexdigest()[:20]
        target = cache_dir / f"pexels_{cache_key}.mp4"
        manifest = target.with_suffix(".json")
        metadata = {
            "provider": "pexels",
            "query": query,
            "video_id": video.get("id"),
            "file_id": source.get("id"),
            "width": source.get("width"),
            "height": source.get("height"),
            "duration": video.get("duration"),
            "page_url": video.get("url"),
            "author": (video.get("user") or {}).get("name"),
            "author_url": (video.get("user") or {}).get("url"),
            "cached": target.is_file() and target.stat().st_size > 0,
        }
        if metadata["cached"]:
            os.utime(target, None)
            metadata["cache_file"] = target.name
            metadata["cached_at"] = time.time()
            query_index.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return str(target), metadata

        with _CACHE_LOCK:
            if not target.is_file() or target.stat().st_size == 0:
                temporary = target.with_suffix(".part")
                total = 0
                max_bytes = 250 * 1024 * 1024
                try:
                    with client.stream("GET", download_url) as download:
                        download.raise_for_status()
                        with open(temporary, "wb") as destination:
                            for chunk in download.iter_bytes(1024 * 1024):
                                total += len(chunk)
                                if total > max_bytes:
                                    raise PexelsError("Pexels video exceeds the 250 MB cache limit")
                                destination.write(chunk)
                    if total == 0:
                        raise PexelsError("Pexels returned an empty video")
                    os.replace(temporary, target)
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise
                manifest.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            _prune_cache(cache_dir, ttl_days, max_gb)
        metadata["cached"] = False
        metadata["cache_file"] = target.name
        metadata["cached_at"] = time.time()
        query_index.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return str(target), metadata
