from music.captions import excerpt_caption_words


def test_excerpt_caption_words_rebases_and_clips_to_excerpt():
    transcript = {"segments": [{"words": [
        {"word": " trước", "start": 8.0, "end": 9.0},
        {"word": " Xin", "start": 10.0, "end": 10.5},
        {"word": " chào", "start": 10.5, "end": 11.1},
        {"word": " bạn", "start": 11.1, "end": 12.2},
        {"word": " sau", "start": 13.0, "end": 13.5},
    ]}]}
    assert excerpt_caption_words(transcript, 10.0, 12.0) == [
        {"text": "Xin", "start": 0.0, "end": 0.5},
        {"text": "chào", "start": 0.5, "end": 1.1},
        {"text": "bạn", "start": 1.1, "end": 2.0},
    ]
