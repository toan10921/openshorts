"""Caption data helpers for a rebased Music Reader excerpt."""


def excerpt_caption_words(transcript, excerpt_start, excerpt_end):
    words = []
    for segment in transcript.get("segments") or []:
        for raw in segment.get("words") or []:
            text = " ".join(str(raw.get("word") or "").split())
            try:
                start = float(raw.get("start"))
                end = float(raw.get("end"))
            except (TypeError, ValueError):
                continue
            if not text or end <= excerpt_start or start >= excerpt_end:
                continue
            words.append({
                "text": text,
                "start": round(max(0.0, start - excerpt_start), 3),
                "end": round(min(excerpt_end, end) - excerpt_start, 3),
            })
    return sorted(words, key=lambda word: (word["start"], word["end"]))
