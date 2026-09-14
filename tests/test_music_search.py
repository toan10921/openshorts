import pytest

from music.search import normalize_text, search_transcript


def _transcript(words):
    return {
        "segments": [{
            "start": words[0][1],
            "end": words[-1][2],
            "text": " ".join(word for word, _, _ in words),
            "words": [
                {"word": word, "start": start, "end": end}
                for word, start, end in words
            ],
        }],
    }


def test_normalize_text_ignores_vietnamese_accents_and_punctuation():
    assert normalize_text("Đừng rời xa anh!") == "dung roi xa anh"


def test_search_finds_a_phrase_despite_asr_spelling_errors():
    transcript = _transcript([
        ("Hạnh", 10.0, 10.4), ("phúc", 10.4, 10.8),
        ("anh", 10.8, 11.1), ("say", 11.1, 11.5),
        ("sao", 11.5, 11.8), ("em", 11.8, 12.1),
        ("lại", 12.1, 12.4), ("vui", 12.4, 12.8),
        ("tay", 12.8, 13.1),
    ])

    results = search_transcript(
        transcript, "hạnh phúc anh xây sao em lại phủi tay", top_k=3,
    )

    assert results
    assert results[0]["start"] == 10.0
    assert results[0]["end"] == 13.1
    assert results[0]["score"] > 0.75


def test_search_returns_separate_chorus_occurrences_not_overlapping_windows():
    phrase = ["xin", "đừng", "rời", "xa", "anh"]
    words = []
    for base in (0.0, 30.0):
        words.extend((word, base + index * 0.4, base + (index + 1) * 0.4)
                     for index, word in enumerate(phrase))
    results = search_transcript(_transcript(words), "xin dung roi xa anh", top_k=5)
    assert len(results) == 2
    assert [result["start"] for result in results] == [0.0, 30.0]


def test_search_rejects_unhelpful_queries():
    transcript = _transcript([("xin", 0, 1)])
    with pytest.raises(ValueError, match="quá ngắn"):
        search_transcript(transcript, "!")
    with pytest.raises(ValueError, match="30 từ"):
        search_transcript(transcript, " ".join(["từ"] * 31))

