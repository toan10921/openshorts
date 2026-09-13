"""Local music transcription pipeline used by the OpenShorts API."""

from .jobs import MusicJobOptions, process_music_job

__all__ = ["MusicJobOptions", "process_music_job"]
