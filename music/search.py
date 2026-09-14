"""Fuzzy lyric search over Whisper's word-level timestamp contract."""

import re
import unicodedata
from difflib import SequenceMatcher


def normalize_text(value):
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _flatten_words(transcript):
    words = []
    for segment in transcript.get("segments") or []:
        for raw in segment.get("words") or []:
            text = " ".join(str(raw.get("word") or "").split())
            normalized = normalize_text(text)
            try:
                start = float(raw.get("start"))
                end = float(raw.get("end"))
            except (TypeError, ValueError):
                continue
            if normalized and end >= start >= 0:
                words.append({
                    "text": text,
                    "normalized": normalized,
                    "start": start,
                    "end": max(end, start + 0.05),
                })
    return words


def _token_f1(query_tokens, candidate_tokens):
    query_set, candidate_set = set(query_tokens), set(candidate_tokens)
    overlap = len(query_set & candidate_set)
    if not overlap:
        return 0.0
    precision = overlap / len(candidate_set)
    recall = overlap / len(query_set)
    return 2 * precision * recall / (precision + recall)


def search_transcript(transcript, query, top_k=5):
    normalized_query = normalize_text(query)
    query_tokens = normalized_query.split()
    if len(normalized_query) < 2 or not query_tokens:
        raise ValueError("Câu tìm kiếm quá ngắn")
    if len(query_tokens) > 30:
        raise ValueError("Câu tìm kiếm không được quá 30 từ")
    words = _flatten_words(transcript)
    if not words:
        return []

    target = len(query_tokens)
    min_window = max(1, target - max(2, target // 3))
    max_window = min(target + max(3, target // 2), 30)
    scored = []
    for size in range(min_window, max_window + 1):
        for offset in range(0, len(words) - size + 1):
            window = words[offset:offset + size]
            candidate = " ".join(word["normalized"] for word in window)
            sequence = SequenceMatcher(None, normalized_query, candidate).ratio()
            token_score = _token_f1(query_tokens, candidate.split())
            score = 0.7 * sequence + 0.3 * token_score
            if score < 0.35:
                continue
            scored.append({
                "start": round(window[0]["start"], 3),
                "end": round(window[-1]["end"], 3),
                "matched_text": " ".join(word["text"] for word in window),
                "score": round(score, 4),
            })

    # Keep the strongest result from overlapping windows so a single chorus
    # occurrence does not fill every slot with near-identical candidates.
    selected = []
    for candidate in sorted(scored, key=lambda item: item["score"], reverse=True):
        overlaps = any(
            min(candidate["end"], existing["end"])
            - max(candidate["start"], existing["start"]) > 0.25
            for existing in selected
        )
        if overlaps:
            continue
        selected.append(candidate)
        if len(selected) >= max(1, min(int(top_k), 10)):
            break
    return selected
