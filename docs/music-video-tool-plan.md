# Kế hoạch triển khai Music Reader & Video Continuity

## Trạng thái triển khai

- **M1 đã có code nền (2026-09-14):** upload qua `upload_id`, job nền có
  progress/manifest, ép ASR tiếng Việt, chuẩn hóa FFmpeg, xuất TXT/JSON/SRT,
  download ZIP, ownership/retention và tab Music Reader trên dashboard.
- **Đã kiểm thử:** unit/API/regression backend và production build dashboard.
- **Lyric excerpt đã có code (2026-09-14):** tìm câu không phụ thuộc dấu tiếng
  Việt, xếp hạng timestamp và nghe preview. Từ candidate đã chọn, xuất WAV tối
  đa 10 giây kết thúc 150 ms sau `candidate.end`; nhờ vậy giữ trọn chữ cuối và
  người dùng tự nối với clip trong phần mềm dựng. Mỗi lần xuất có JSON plan.
- **Ghép video vẫn là lựa chọn song song:** dùng đúng range của WAV ở trên rồi
  nối với Existing OpenShort (mặc định) hoặc video upload thủ công. Vì hai hành
  động dùng chung `candidate.end + 150 ms`, preview/export/render không lệch mốc.
- **Caption phần nhạc đã có code:** mặc định burn karaoke caption theo preset
  OpenShorts chỉ trong đoạn intro; word timestamp được rebase về 0. Render plan
  giữ danh sách word và URL tải ASS/SRT để tiếp tục chỉnh sửa bên ngoài.
- **Timelapse hook visual đã có code:** Pexels portrait search + local query
  cache, crop/loop đúng duration hook, bỏ audio stock và giữ nguyên sound hook.
  Query cấu hình được trên UI; lỗi API/download tự fallback về frame đầu clip.
- **Còn lại trong M1:** benchmark transcription thật trên RTX 3060 bằng bộ file
  mẫu tiếng Việt và tinh chỉnh preset theo VRAM 6 GB hoặc 12 GB.
- **Chưa triển khai:** Demucs/LRC/editor (M2), TTS (M3) và Video Continuity
  (M4–M5).

## 1. Mục tiêu và cách hiểu yêu cầu

Tính năng mới có hai năng lực độc lập nhưng dùng chung hạ tầng media của
OpenShorts:

1. **Music Reader**: người dùng đưa vào một tệp âm thanh/video mà họ có quyền
   sử dụng. Hệ thống chạy cục bộ trên GPU NVIDIA để tách giọng hát, nhận dạng
   lời tiếng Việt, cho phép sửa lời, rồi xuất TXT/SRT/LRC và tùy chọn một file
   giọng đọc tiếng Việt.
2. **Video Continuity** (giai đoạn sau): lấy một đoạn ngắn ở **cuối clip A**
   đã xuất từ OpenShorts làm tín hiệu ngữ cảnh, tìm phần mở đầu phù hợp của
   clip/video B, rồi ghép A → B. Kết quả cần có cảm giác liền mạch về hình,
   âm thanh và nội dung. Ưu tiên tuyệt đối là nối lại từ đúng source video và
   timecode gốc; tìm bằng AI chỉ là phương án khi không còn source chung.

Ví dụ mong muốn:

```text
OpenShorts clip A                 OpenShorts candidate B/source B
  ... [đoạn cuối 2 giây]     +     [đoạn đầu phù hợp] ...
                │                         │
                └──── continuity engine ──┘
                              │
                         video A → B.mp4
```

Phần “tải nhạc” chỉ phục vụ nguồn mà người dùng được phép tải hoặc sử dụng.
MVP nên ưu tiên upload file. Không triển khai chức năng vượt DRM hay vượt điều
khoản của nền tảng nguồn.

## 2. Quyết định kiến trúc

Không dựng một ứng dụng độc lập. Tính năng nằm trong backend và dashboard
hiện có:

```text
dashboard (React/Vite)
       │ REST + polling
app.py (FastAPI, hàng đợi job sẵn có)
       │
music/ ── FFmpeg ── Demucs ── faster-whisper ── export/TTS
       │
continuity/ ── OpenShorts project metadata ── match ── FFmpeg compose
       │
uploads/                  output/<job_id>/music hoặc continuity/
```

Các điểm tái sử dụng bắt buộc:

- `app.py`: upload, quyền sở hữu job, hàng đợi và cơ chế polling status.
- `transcribe_backends.py`: singleton `faster-whisper`, CUDA gate và format
  transcript chuẩn (`text`, `language`, `segments`, `words`).
- `subtitles.py`: tạo SRT/ASS; Music Reader thêm LRC nhưng không thay đổi các
  contract hiện tại.
- `ffmpeg_utils.py`: codec, metadata scrub và chuẩn lệnh FFmpeg.
- metadata clip đang được ghi trong `output/<job_id>/`: dùng để biết source,
  start/end, layout và transcript của clip OpenShorts.

Không sửa contract `/api/process` hay format metadata clip hiện có trong MVP.
Music và continuity có job type riêng để không rủi ro pipeline tạo Shorts.

## 3. Phạm vi, theo thứ tự triển khai

| Mốc | Có | Chưa làm |
| --- | --- | --- |
| M1 — Music transcript | Upload audio/video, nhận dạng tiếng Việt bằng GPU, TXT/JSON/SRT | URL downloader, Demucs, TTS, UI chỉnh lời |
| M2 — Lyrics tốt hơn | Tách vocal, LRC, editor, retry, download ZIP | Căn lời theo bản lyric ngoài hệ thống |
| M3 — Đọc lời | TTS local từ lyric đã được duyệt | Clone giọng, dịch lời tự động |
| M4 — Continuity nguồn chung | Nối clip OpenShorts cùng source/timecode | Tìm video khác source |
| M5 — Continuity tìm kiếm | Lập chỉ mục và xếp hạng candidate khác source | Tự xuất/publish không cần người duyệt |

M1 là điểm bắt đầu hợp lý. Nó nhỏ, có thể kiểm thử hoàn toàn bằng file mẫu và
RTX 3060, đồng thời kiểm chứng pipeline tiếng Việt trước khi đầu tư vào Demucs.

## 4. Cấu trúc thư mục đề xuất

Tạo các package mới, không nhét logic media mới trực tiếp vào `app.py`:

```text
music/
  __init__.py
  models.py             # Pydantic/dataclass; trạng thái và artifact
  jobs.py               # orchestration MusicJob
  media.py              # ffprobe, chuẩn hóa audio với FFmpeg
  vocals.py             # adapter Demucs, chỉ gọi ở M2
  transcript.py         # gọi transcribe_media(), chuẩn hóa tiếng Việt
  lyrics.py             # TXT/SRT/LRC, validation timestamp
  tts.py                # interface TTS; Piper implementation ở M3
  storage.py            # đường dẫn artifact, manifest.json

continuity/
  __init__.py
  models.py             # ClipRef, TailContext, Candidate, JoinPlan
  openshorts.py         # đọc/validate metadata job hiện hữu
  extract.py            # cắt tail/head theo timecode, tạo proxy
  same_source.py        # chiến lược chính xác cho source chung
  index.py              # manifest + index candidate, M5
  match.py              # score audio/visual/text, M5
  compose.py            # hard cut / xfade / acrossfade / render final
  quality.py            # kiểm tra duration, A/V sync, black frame, audio peak

tests/
  test_music_lyrics.py
  test_music_jobs.py
  test_continuity_same_source.py
  test_continuity_match.py
  fixtures/
```

`uploads/` và `output/` là dữ liệu runtime, không commit. Mọi artifact cần
`manifest.json` cạnh kết quả để khi backend khởi động lại vẫn khôi phục được
trạng thái.

## 5. Contract dữ liệu Music Reader

### 5.1 Trạng thái job

```json
{
  "id": "music_01J...",
  "type": "music",
  "status": "queued",
  "stage": "normalize",
  "progress": 0,
  "source": {"kind": "upload", "filename": "bai-hat.mp3"},
  "options": {
    "language": "vi",
    "separate_vocals": false,
    "model": "medium",
    "create_tts": false
  },
  "artifacts": {},
  "error": null,
  "created_at": "2026-09-14T00:00:00Z"
}
```

Trạng thái hợp lệ: `queued → running → completed | failed | cancelled`.
`stage` lần lượt là `validate`, `normalize`, `separate_vocals`, `transcribe`,
`export`, `tts` và `complete`. Chỉ một job được dùng GPU cho ASR tại một thời
điểm theo `ASR_GPU_CONCURRENCY=1`; Demucs cũng phải có semaphore riêng, mặc
định `MUSIC_GPU_CONCURRENCY=1`.

### 5.2 Transcript và lyric

Giữ transcript chuẩn của repo. Bổ sung manifest lyric riêng, không làm hỏng
subtitle format:

```json
{
  "version": 1,
  "language": "vi",
  "transcript": "...",
  "lines": [
    {"id": "l001", "start": 0.42, "end": 4.82, "text": "...", "confidence": 0.87}
  ],
  "source": "asr",
  "edited_at": null
}
```

Quy tắc dữ liệu:

- Timestamp là giây tuyệt đối, số thực; line phải có `0 ≤ start < end`.
- Các line theo thứ tự thời gian; line edit không tự thay đổi timestamp trừ khi
  endpoint chuyên dụng yêu cầu.
- LRC ghi centisecond: `[mm:ss.cc]`, một line một mốc bắt đầu.
- Bản người dùng sửa là nguồn chân lý cho export và TTS, không bị job retry ghi
  đè. Transcript ASR thô giữ ở artifact khác để audit.

### 5.3 API đề xuất

Các endpoint cần xác thực/chủ sở hữu giống endpoint job hiện tại:

| Method/path | Mục đích |
| --- | --- |
| `POST /api/music/jobs` | Tạo job từ `upload_id`, options JSON |
| `GET /api/music/jobs/{id}` | Poll trạng thái, progress và artifact URLs |
| `POST /api/music/jobs/{id}/search` | Tìm các timestamp của một câu lyric, fuzzy match theo word timestamp |
| `GET /api/music/jobs/{id}/preview` | Render audio preview tối đa 30 giây quanh candidate |
| `POST /api/music/jobs/{id}/excerpt` | Xuất WAV 10 giây giữ trọn chữ cuối và 150 ms âm đuôi |
| `POST /api/music/overlay` | Thêm 10 giây nhạc trước candidate vào OpenShorts và lưu render plan |
| `GET /api/music/jobs/{id}/lyrics` | Đọc lyric manifest |
| `PUT /api/music/jobs/{id}/lyrics` | Lưu toàn bộ lyric đã sửa, validate version |
| `POST /api/music/jobs/{id}/exports` | Tạo lại `txt`, `srt`, `lrc`, hoặc `tts` từ lyric hiện hành |
| `GET /api/music/jobs/{id}/download` | ZIP artifact đã có |
| `DELETE /api/music/jobs/{id}` | Xóa job/artifact theo quy tắc retention |

Không nhận đường dẫn máy local từ client. Client chỉ gửi `upload_id`; backend
xác nhận upload thuộc user hiện tại trước khi di chuyển sang thư mục job.

## 6. Pipeline M1 — transcript tiếng Việt local

### 6.1 Validate và chuẩn hóa

1. Chấp nhận `mp3`, `m4a`, `wav`, `flac`, `mp4`, `mov`, `webm`; xác minh MIME
   và dùng `ffprobe`, không tin extension.
2. Áp dụng `MAX_FILE_SIZE_MB`; dùng timeout của subprocess, tuyệt đối không
   `shell=True`.
3. Tách audio thành `normalized.wav`: mono, 16 kHz, PCM s16le.
4. Ghi `source.json` gồm SHA-256, duration, codec, file size; hash giúp tránh
   xử lý lại cùng tệp về sau.

Lệnh (phải xây bằng list argument trong code):

```bash
ffmpeg -y -i INPUT -vn -ac 1 -ar 16000 -c:a pcm_s16le normalized.wav
```

### 6.2 Nhận dạng

`music/transcript.py` gọi `transcribe_backends.transcribe_media()` thay vì tạo
`WhisperModel` mới. Cần mở rộng hàm backend để hỗ trợ một profile an toàn:

```python
MusicASROptions(
    language="vi",
    beam_size=5,
    vad_filter=True,
    word_timestamps=True,
    condition_on_previous_text=False,
)
```

Với RTX 3060:

- 12 GB VRAM: bắt đầu `WHISPER_MODEL=medium`, `WHISPER_DEVICE=cuda`,
  `WHISPER_COMPUTE=float16`.
- 6 GB VRAM: `small`, `float16` hoặc `int8_float16` sau khi benchmark.
- Đừng mặc định `large-v3`: thử sau, chỉ khi benchmark cho thấy đủ VRAM và tốc
  độ đáp ứng. Không để model ASR và Demucs cùng giữ VRAM trong cùng một stage.

MVP phải trả cảnh báo rõ ràng: ASR lời hát không bảo đảm đúng tuyệt đối; rap,
auto-tune, bè dày và hòa âm có thể sai. Không tự nhận đây là lyric chính thức.

### 6.3 Export

- TXT: plain text, một line lyric trên một dòng.
- JSON: lyric manifest ở trên.
- SRT: dùng helper hiện có hoặc adapter từ `lines`.
- LRC: chỉ từ M2 trở đi, nhưng format adapter có thể viết sẵn ở M1.

## 7. M2 và M3 — cải thiện lời hát, TTS

### 7.1 Tách vocal

Demucs là tùy chọn `separate_vocals=true`:

```text
normalized input → demucs → vocals.wav → ASR
                           └→ accompaniment.wav (giữ nếu người dùng tải)
```

Nếu Demucs lỗi/OOM, job không thất bại hoàn toàn: ghi warning và fallback ASR
trên `normalized.wav`. Không chạy Demucs đồng thời với Whisper; giải phóng
process/model sau stage hoặc serialize hai stage qua GPU semaphore.

### 7.2 Sửa lyric

UI `dashboard/src/components/MusicReader.jsx` gồm:

- upload và lựa chọn “tách vocal”; model chỉ có preset `balanced`/`fast`, không
  phơi toàn bộ flag kỹ thuật;
- audio player với line hiện hành highlight theo currentTime;
- textarea/list editor theo từng line, nút lưu rõ ràng;
- download TXT/SRT/LRC và “tạo giọng đọc”.

Không tự lấy lyric từ website bên ngoài. Nếu sau này có import lyric do người
dùng cung cấp, phải ghi `source: user_import` và có trang xác nhận quyền dùng.

### 7.3 Đọc tiếng Việt

Định nghĩa interface để dễ thay Piper/VITS mà không chạm API:

```python
class TTSEngine(Protocol):
    def synthesize(self, text: str, language: str, output_wav: Path) -> None: ...
```

TTS đọc **lyric đã chỉnh sửa**, theo từng line, chèn silence từ timestamp nếu
người dùng chọn “giữ timing”. Mặc định là đọc liên tục để tránh việc nhận dạng
timestamp sai khiến giọng đọc gãy. Không làm clone giọng khi chưa có flow xác
nhận consent riêng.

## 8. Video Continuity — định nghĩa đúng bài toán

Một hard cut chỉ có thể “liền” nếu B thật sự là phần tiếp theo của A hoặc có
chủ ý dựng. Vì thế engine phải trả về **đề xuất có thể giải thích được**, không
im lặng tự ghép rồi xuất bản.

`TailContext` lấy từ clip A:

```json
{
  "clip_ref": {"job_id": "jobA", "clip_index": 2},
  "tail_seconds": 2.0,
  "source_video_id": "sha256:...",
  "source_end": 91.840,
  "tail_audio_fingerprint": "...",
  "tail_frame_embeddings": ["..."],
  "tail_transcript": "..."
}
```

`Candidate` luôn chứa lý do và confidence:

```json
{
  "id": "jobB:clip:0",
  "start": 0.0,
  "score": 0.94,
  "strategy": "same_source_adjacent",
  "reasons": ["same source hash", "source timecodes adjacent: 91.84 → 91.87"],
  "transition": {"kind": "hard_cut", "duration": 0.0}
}
```

Ngưỡng UX: `>=0.90` mặc định chọn nhưng vẫn preview; `0.65–0.89` hiện để người
dùng chọn; `<0.65` không tự đề xuất là “liền mạch”.

## 9. M4 — nối chính xác clip có source chung

Đây là phần nên làm đầu tiên cho continuity. Nó không cần AI vision và mang
chất lượng cao nhất.

1. Người dùng chọn clip A và phạm vi candidate (một job, nhiều job, hoặc
   source video hiện tại).
2. `continuity/openshorts.py` xác minh quyền sở hữu hai job và đọc metadata.
3. Nếu `source_video_id` hash giống nhau, tìm candidate có `candidate.start`
   gần `A.source_end`, trong tolerance mặc định 0.25 s.
4. Nếu đúng source và liền timecode, **không nối hai video đã render**. Cắt
   một đoạn nguồn liên tục từ `A.source_start` tới `B.source_end`, sau đó gọi
   lại renderer với recipe/layout đã chọn. Điều này tránh double-encode,
   lệch subtitle và frame discontinuity.
5. Nếu layout/style A và B khác nhau, render hai đoạn riêng, cắt ở scene cut
   an toàn gần nhất, rồi mới compose. UI phải báo transition style.
6. Chỉ dùng hard cut khi source frames continuous; dùng `xfade` rất ngắn
   (0.08–0.18 s) và `acrossfade` (0.05–0.12 s) khi có scene/audio discontinuity.

`JoinPlan` phải là dữ liệu có thể reproduce:

```json
{
  "version": 1,
  "left": {"job_id": "jobA", "clip_index": 2, "in": 65.2, "out": 91.84},
  "right": {"job_id": "jobB", "clip_index": 0, "in": 91.84, "out": 115.7},
  "source_mode": "single_source_rerender",
  "transition": {"kind": "hard_cut", "at": 26.64},
  "subtitle_policy": "rebuild_from_source_transcript"
}
```

Subtitle policy là bắt buộc: ghép file SRT cũ dễ tạo offset sai. Phải lọc word
timestamps từ transcript nguồn theo range mới rồi build subtitle từ đầu.

## 10. M5 — tìm candidate khác source

Chỉ thực hiện sau khi M4 ổn định. Đây là xếp hạng candidate, không phải cam kết
ngữ nghĩa tuyệt đối.

### 10.1 Index local

Mỗi output clip do người dùng sở hữu có `continuity_index.json`:

- `source_id`, job/clip ref, duration, fps, width/height;
- 3–5 keyframe ở 0.0–2.0 giây đầu và 1–3 keyframe cuối;
- audio fingerprint của 2 giây đầu/cuối (Chromaprint hoặc embedding local);
- transcript đầu/cuối và text embedding local (tùy chọn);
- scene-cut score, loudness LUFS, speech/music flag.

Không upload embedding/file sang dịch vụ ngoài. Mọi index nằm trong output của
chủ sở hữu và bị xóa cùng retention policy.

### 10.2 Xếp hạng

Điểm tổng chỉ dùng các tín hiệu có lý do hiển thị được:

```text
score = 0.45 × visual_continuity
      + 0.30 × audio_continuity
      + 0.15 × transcript_continuation
      + 0.10 × format_compatibility
```

- `visual_continuity`: embedding keyframe (CLIP/DINO local), màu, face/person
  continuity và motion direction. Nếu shot khác hẳn, score phải thấp.
- `audio_continuity`: audio overlap/fingerprint, loudness delta và speech/music
  class. Bản ghi âm khác không được giả vờ là seamless.
- `transcript_continuation`: embedding/lexical continuation của cuối A và đầu
  B. Chỉ là tín hiệu phụ vì ASR có thể sai.
- `format_compatibility`: aspect ratio, fps, resolution, caption style/layout.

Trước khi render final, tạo preview 4–6 giây tại điểm nối và cho người dùng
chọn candidate/transition. Không tự publish artifact này.

## 11. API Continuity

| Method/path | Mục đích |
| --- | --- |
| `POST /api/continuity/candidates` | Input clip A + scope + tail seconds; trả candidate xếp hạng |
| `POST /api/continuity/preview` | Input JoinPlan; render preview ngắn quanh điểm nối |
| `POST /api/continuity/render` | Render final từ JoinPlan người dùng đã xác nhận |
| `GET /api/continuity/jobs/{id}` | Poll render job |
| `GET /api/continuity/jobs/{id}/plan` | Đọc JoinPlan để sửa/reproduce |

Request của endpoint candidates:

```json
{
  "left": {"job_id": "jobA", "clip_index": 2},
  "scope": {"kind": "jobs", "job_ids": ["jobB", "jobC"]},
  "tail_seconds": 2.0,
  "max_candidates": 12
}
```

Backend kiểm tra ownership cho **tất cả** job trong input; không cho phép
enumerate output/metadata của người khác qua candidate score hay preview URL.

## 12. Thay đổi hạ tầng và cấu hình

Biến môi trường đề xuất (đều có default an toàn):

```dotenv
# GPU ASR hiện có
WHISPER_MODEL=medium
WHISPER_DEVICE=cuda
WHISPER_COMPUTE=float16
ASR_GPU_CONCURRENCY=1

# Music mới
MUSIC_ENABLED=true
MUSIC_GPU_CONCURRENCY=1
MUSIC_MAX_DURATION_SECONDS=3600
MUSIC_DEMUCS_MODEL=htdemucs
MUSIC_TTS_ENABLED=false

# Continuity mới
CONTINUITY_ENABLED=false
CONTINUITY_MAX_TAIL_SECONDS=5
CONTINUITY_INDEX_ENABLED=false
```

Docker cần NVIDIA runtime cho backend khi chạy GPU. Không cài model hay tải
trọng số lúc import module; lazy-load ở stage cần thiết và mount cache model
vào volume bền vững. Bổ sung health readiness chỉ khi feature được bật, để
việc thiếu Demucs/Piper không làm hỏng Clip Generator hiện hữu.

## 13. Bảo mật, quyền và retention

- Chỉ xử lý media người dùng upload hoặc nguồn mà họ xác nhận có quyền dùng.
- Validate path bằng path đã tạo từ `job_id` UUID; không ghép raw filename vào
  command/filtergraph FFmpeg.
- Giới hạn duration, kích thước, subprocess timeout và disk quota trước khi
  chạy Demucs/FFmpeg.
- Job/artifact dùng cùng `JOB_RETENTION_SECONDS`, quota và authorization với
  OpenShorts; dọn cả index/proxy/preview liên quan.
- Chỉ cho continuity dùng project của cùng owner (hoặc có cơ chế share rõ
  ràng về sau).
- Log không ghi nội dung lyric đầy đủ; log job chỉ stage, duration, model,
  error code và artifact path đã sanitize.

## 14. Kiểm thử và tiêu chí hoàn thành

### M1

- Unit: LRC rounding, validation timestamp, artifact path không escape job dir.
- Unit: music options mặc định `language=vi`, transcript adapter không làm đổi
  word timestamps.
- Integration: upload fixture WAV → job completed → TXT/JSON/SRT tồn tại và
  JSON hợp schema.
- Integration: media lỗi, file không audio, timeout FFmpeg và CUDA OOM trả lỗi
  có thể hiểu được, không bỏ semaphore.
- Manual GPU: RTX 3060 chạy 3 bài (giọng rõ, hòa âm dày, rap); ghi latency,
  VRAM peak và đánh giá lyric. Chỉ nâng model sau số liệu này.
- Integration cầu nối: fuzzy search giữ timestamp word-level; preview đúng
  range; FFmpeg mix/replace vẫn giữ nguyên duration và audio stream của Short.

### M4

- Unit: cùng source + timecode adjacent tạo `single_source_rerender`.
- Unit: source hash khác không được đi qua path same-source.
- Integration: render join, audio/video duration sai lệch < 1 frame; subtitle
  timecode bắt đầu từ 0 và không vượt duration final.
- Manual: preview đúng tail A + head B, không black frame, không audio pop
  rõ rệt và download final hoạt động.

## 15. Checklist triển khai đầu tiên

1. Tạo package `music/` và Pydantic model/job manifest.
2. Thêm `POST/GET /api/music/jobs` cùng ownership/queue pattern hiện có.
3. Dùng upload flow sẵn có, ffprobe/FFmpeg chuẩn hóa vào `output/<music-id>`.
4. Adapter gọi `transcribe_media()` với tiếng Việt; tạo TXT/JSON/SRT.
5. Thêm tab dashboard Music Reader, polling và download artifact — chưa cần
   lyric editor.
6. Viết tests M1 và benchmark RTX 3060.
7. Sau M1 ổn định: Demucs, LRC/editor, TTS.
8. Sau đó mới xây `continuity/` M4 theo source/timecode; không nhảy thẳng sang
   embedding search M5.

## 16. Câu hỏi cần chốt trước khi bắt đầu code M1

Các quyết định mặc định đề xuất là: upload-only, Vietnamese forced (`vi`),
`medium` trên RTX 3060 12 GB, không Demucs ở MVP, không TTS ở MVP và artifact
theo retention hiện hữu. Nếu máy có RTX 3060 6 GB, preset đổi sang `small`.

Khi bắt đầu M4, cần chốt thêm liệu “video B” là clip khác trong cùng project,
bất cứ output nào của cùng user, hay một file upload mới. Thiết kế API trên đã
hỗ trợ cả ba, nhưng MVP nên giới hạn cùng OpenShorts project/source để giữ kết
quả có tính liền mạch thực sự.
