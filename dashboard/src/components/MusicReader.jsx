import React, { useEffect, useRef, useState } from 'react';
import { Download, FileAudio, Film, Loader2, Music2, Play, RotateCcw, Scissors, Search, Sparkles, Upload, X } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';
import { getApiUrl } from '../config';

const TERMINAL = new Set(['completed', 'failed']);
const ACTIVE_MUSIC_JOB_KEY = 'openshorts_music_job_id';
const NEW_MUSIC_JOB = '__new__';

const errorText = (error, fallback) => error?.detail || error?.message || fallback;

const timestamp = (seconds) => {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(Math.floor(value % 60)).padStart(2, '0')}.${String(Math.round((value % 1) * 10) % 10)}`;
};

export default function MusicReader({ shortJobId = null, shortClips = [] }) {
  const [file, setFile] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState(null);
  const [lyrics, setLyrics] = useState(null);
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState(false);
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState(null);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewing, setPreviewing] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [excerptResult, setExcerptResult] = useState(null);
  const [videoSource, setVideoSource] = useState('openshort');
  const [clipIndex, setClipIndex] = useState(0);
  const [externalVideo, setExternalVideo] = useState(null);
  const [videoConfirmed, setVideoConfirmed] = useState(false);
  const [lyricCaptions, setLyricCaptions] = useState(true);
  const [hookVisual, setHookVisual] = useState('pexels');
  const [visualQuery, setVisualQuery] = useState('city timelapse');
  const [joining, setJoining] = useState(false);
  const [joinResult, setJoinResult] = useState(null);
  const pollTimer = useRef(null);

  useEffect(() => () => clearTimeout(pollTimer.current), []);
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  useEffect(() => {
    if (clipIndex >= shortClips.length) setClipIndex(0);
  }, [clipIndex, shortClips.length]);

  useEffect(() => {
    const savedJobId = localStorage.getItem(ACTIVE_MUSIC_JOB_KEY);
    if (savedJobId === NEW_MUSIC_JOB) return;
    const path = savedJobId
      ? `/api/music/jobs/${savedJobId}`
      : '/api/music/jobs/latest';
    apiJson(path)
      .then((restored) => {
        setJob(restored);
        localStorage.setItem(ACTIVE_MUSIC_JOB_KEY, restored.id);
      })
      .catch(() => {
        if (savedJobId) localStorage.removeItem(ACTIVE_MUSIC_JOB_KEY);
      });
  }, []);

  useEffect(() => {
    if (!job?.id || TERMINAL.has(job.status)) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await apiJson(`/api/music/jobs/${job.id}`);
        if (cancelled) return;
        setJob(next);
        if (!TERMINAL.has(next.status)) pollTimer.current = setTimeout(poll, 1200);
      } catch (e) {
        if (!cancelled) setError(errorText(e, 'Could not read job status.'));
      }
    };
    pollTimer.current = setTimeout(poll, 500);
    return () => {
      cancelled = true;
      clearTimeout(pollTimer.current);
    };
  }, [job?.id, job?.status]);

  useEffect(() => {
    const url = job?.result?.artifacts?.json;
    if (job?.status !== 'completed' || !url) return;
    apiJson(url).then(setLyrics).catch((e) => setError(errorText(e, 'Could not load lyrics.')));
  }, [job?.status, job?.result?.artifacts?.json]);

  const start = async () => {
    if (!file || !confirmed || uploadProgress) return;
    setError('');
    setLyrics(null);
    setUploadProgress(true);
    let reservedUploadId = null;
    try {
      const slot = await apiJson('/api/uploads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name }),
      });
      reservedUploadId = slot.upload_id;
      // upload_url is absolute for CLI/MCP clients. Behind Vite/Docker it can
      // contain the private `backend:8000` hostname, which a browser cannot
      // resolve. The dashboard must use its same-origin /api proxy instead.
      const uploaded = await apiFetch(`/api/uploads/${slot.upload_id}`, { method: 'PUT', body: file });
      if (!uploaded.ok) {
        const body = await uploaded.json().catch(() => ({}));
        throw new Error(body.detail || 'Audio upload failed.');
      }
      const created = await apiJson('/api/music/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: slot.upload_id, language: 'vi' }),
      });
      setJob(created);
      localStorage.setItem(ACTIVE_MUSIC_JOB_KEY, created.id);
      reservedUploadId = null; // consumed by POST /api/music/jobs
    } catch (e) {
      if (reservedUploadId) {
        apiFetch(`/api/uploads/${reservedUploadId}`, { method: 'DELETE' }).catch(() => {});
      }
      setError(errorText(e, 'Could not start Music Reader.'));
    } finally {
      setUploadProgress(false);
    }
  };

  const download = async (url, filename) => {
    try {
      const response = await apiFetch(url);
      if (!response.ok) throw new Error('Download failed.');
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (e) {
      setError(errorText(e, 'Download failed.'));
    }
  };

  const searchLyrics = async (event) => {
    event?.preventDefault();
    if (!job?.id || !query.trim() || searching) return;
    setError('');
    setSearching(true);
    setSelected(null);
    setCandidates([]);
    setHasSearched(false);
    setExcerptResult(null);
    setJoinResult(null);
    try {
      const data = await apiJson(`/api/music/jobs/${job.id}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), top_k: 5 }),
      });
      setCandidates(data.candidates || []);
      if ((data.candidates || []).length) setSelected(data.candidates[0]);
      setHasSearched(true);
    } catch (e) {
      setError(errorText(e, 'Could not search the transcript.'));
    } finally {
      setSearching(false);
    }
  };

  const preview = async (candidate) => {
    if (!candidate || previewing) return;
    setError('');
    setSelected(candidate);
    setExcerptResult(null);
    setJoinResult(null);
    setPreviewing(true);
    try {
      const response = await apiFetch(
        `/api/music/jobs/${job.id}/preview?start=${candidate.start}&end=${candidate.end}&padding=0.25`,
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || 'Could not create preview.');
      }
      const nextUrl = URL.createObjectURL(await response.blob());
      setPreviewUrl(nextUrl);
    } catch (e) {
      setError(errorText(e, 'Could not create preview.'));
    } finally {
      setPreviewing(false);
    }
  };

  const exportExcerpt = async () => {
    if (!selected || extracting) return;
    setError('');
    setExtracting(true);
    setExcerptResult(null);
    try {
      const data = await apiJson(`/api/music/jobs/${job.id}/excerpt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          match_start: selected.start,
          match_end: selected.end,
          query: query.trim(),
          matched_text: selected.matched_text,
          match_score: selected.score,
          excerpt_seconds: 10,
          tail_padding: 0.15,
        }),
      });
      setExcerptResult(data);
    } catch (e) {
      setError(errorText(e, 'Could not export the music excerpt.'));
    } finally {
      setExtracting(false);
    }
  };

  const joinToVideo = async () => {
    const existingReady = videoSource === 'openshort' && shortJobId && shortClips.length;
    const uploadReady = videoSource === 'upload' && externalVideo && videoConfirmed;
    if (!selected || (!existingReady && !uploadReady) || joining) return;
    setError('');
    setJoining(true);
    setJoinResult(null);
    let reservedUploadId = null;
    try {
      if (videoSource === 'upload') {
        const slot = await apiJson('/api/uploads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: externalVideo.name }),
        });
        reservedUploadId = slot.upload_id;
        const uploaded = await apiFetch(`/api/uploads/${slot.upload_id}`, {
          method: 'PUT', body: externalVideo,
        });
        if (!uploaded.ok) {
          const body = await uploaded.json().catch(() => ({}));
          throw new Error(body.detail || 'Video upload failed.');
        }
      }
      const data = await apiJson('/api/music/overlay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          music_job_id: job.id,
          video_source: videoSource,
          video_job_id: videoSource === 'openshort' ? shortJobId : null,
          clip_index: Number(clipIndex),
          video_upload_id: reservedUploadId,
          video_acknowledged: videoSource === 'upload' ? videoConfirmed : false,
          start: selected.start,
          end: selected.end,
          query: query.trim(),
          matched_text: selected.matched_text,
          match_score: selected.score,
          lead_seconds: 10,
          tail_padding: 0.15,
          lyric_captions: lyricCaptions,
          hook_visual: hookVisual,
          visual_query: visualQuery.trim() || 'city timelapse',
        }),
      });
      setJoinResult(data);
      reservedUploadId = null;
    } catch (e) {
      if (reservedUploadId) {
        apiFetch(`/api/uploads/${reservedUploadId}`, { method: 'DELETE' }).catch(() => {});
      }
      setError(errorText(e, 'Could not join the music excerpt to the video.'));
    } finally {
      setJoining(false);
    }
  };

  const reset = () => {
    clearTimeout(pollTimer.current);
    setFile(null);
    setConfirmed(false);
    setJob(null);
    setLyrics(null);
    setQuery('');
    setCandidates([]);
    setSelected(null);
    setHasSearched(false);
    setPreviewUrl('');
    setExcerptResult(null);
    setVideoSource('openshort');
    setClipIndex(0);
    setExternalVideo(null);
    setVideoConfirmed(false);
    setLyricCaptions(true);
    setHookVisual('pexels');
    setVisualQuery('city timelapse');
    setJoinResult(null);
    localStorage.setItem(ACTIVE_MUSIC_JOB_KEY, NEW_MUSIC_JOB);
    setError('');
  };

  const busy = uploadProgress || (job && !TERMINAL.has(job.status));

  return (
    <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
      <div className="max-w-3xl mx-auto p-4 sm:p-6 md:p-8">
        <div className="mb-7">
          <p className="eyebrow mb-1.5">06 · MUSIC READER</p>
          <h1 className="font-display lowercase text-3xl text-ink">read Vietnamese lyrics locally</h1>
          <p className="text-sm text-muted mt-3 max-w-2xl leading-relaxed">
            Upload audio or video. Your NVIDIA GPU transcribes the Vietnamese vocals and creates TXT, JSON and SRT files.
          </p>
        </div>

        {!job && (
          <div className="card p-5 sm:p-6">
            <label className={`block border-2 border-dashed rounded-card p-8 text-center cursor-pointer transition-colors ${file ? 'border-brass' : 'border-rule2 hover:border-brass'}`}>
              <input
                type="file"
                accept="audio/*,video/mp4,video/webm,video/quicktime"
                className="hidden"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              {file ? (
                <span className="flex items-center justify-center gap-3 min-w-0 text-ink2">
                  <FileAudio size={18} className="text-brass shrink-0" />
                  <span className="truncate">{file.name}</span>
                  <button type="button" onClick={(event) => { event.preventDefault(); setFile(null); }} className="p-1 text-muted hover:text-ink">
                    <X size={16} />
                  </button>
                </span>
              ) : (
                <>
                  <Music2 size={20} className="mx-auto mb-3 text-muted" />
                  <span className="block text-ink2 lowercase">choose an audio or video file</span>
                  <span className="readout block mt-2">MP3 · M4A · WAV · FLAC · MP4 · WEBM</span>
                </>
              )}
            </label>

            <label className="flex items-start gap-3 mt-5 text-sm text-muted cursor-pointer">
              <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-[var(--color-accent)]" />
              <span>I own this media or have permission to process it.</span>
            </label>

            <button onClick={start} disabled={!file || !confirmed || uploadProgress} className="btn-primary mt-5 px-5 py-2.5 disabled:opacity-40 disabled:cursor-not-allowed">
              {uploadProgress ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
              {uploadProgress ? 'uploading' : 'transcribe locally'}
            </button>
          </div>
        )}

        {job && (
          <div className="space-y-4">
            <div className="card p-5 sm:p-6">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="eyebrow">{job.status === 'completed' ? 'COMPLETE' : job.status === 'failed' ? 'FAILED' : 'PROCESSING'}</p>
                  <p className="text-ink mt-2">{job.source?.filename}</p>
                </div>
                {busy && <Loader2 size={18} className="animate-spin text-brass shrink-0" />}
              </div>
              <div className="h-1.5 bg-paper3 rounded-full overflow-hidden mt-5">
                <div className="h-full bg-brass transition-all duration-200" style={{ width: `${job.progress || 0}%` }} />
              </div>
              <div className="flex justify-between mt-2">
                <span className="readout">{String(job.stage || 'queued').replaceAll('_', ' ')}</span>
                <span className="readout">{job.progress || 0}%</span>
              </div>
              {job.status === 'failed' && <p className="text-sm text-danger mt-4">{job.error || 'Transcription failed.'}</p>}
            </div>

            {job.status === 'completed' && (
              <div className="card p-5 sm:p-6">
                <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                  <div>
                    <p className="eyebrow">VIETNAMESE TRANSCRIPT</p>
                    <p className="text-xs text-muted mt-1">{job.result?.line_count || 0} lines · machine transcription, review before publishing</p>
                  </div>
                  <button onClick={() => download(job.result.download, 'music-reader-results.zip')} className="btn-primary px-4 py-2 text-sm">
                    <Download size={15} /> download all
                  </button>
                </div>
                {(job.result?.warnings || []).map((warning) => (
                  <p key={warning} className="badge-warn normal-case px-3 py-2 rounded-input mb-3 text-xs">
                    {warning}
                  </p>
                ))}
                <div className="max-h-80 overflow-y-auto custom-scrollbar bg-paper rounded-input border border-rule p-4 space-y-3">
                  {(lyrics?.lines || []).map((line) => (
                    <div key={line.id} className="grid grid-cols-[4.5rem_1fr] gap-3 text-sm">
                      <span className="font-mono text-xs text-muted tabular-nums pt-0.5">{line.start.toFixed(2)}s</span>
                      <span className="text-ink2">{line.text}</span>
                    </div>
                  ))}
                  {!lyrics && <p className="text-sm text-muted">Loading transcript…</p>}
                </div>
                <div className="flex flex-wrap gap-2 mt-4">
                  {['txt', 'srt', 'json'].map((kind) => job.result?.artifacts?.[kind] && (
                    <button key={kind} onClick={() => download(job.result.artifacts[kind], `lyrics.${kind}`)} className="btn-quiet px-3 py-2 text-xs">
                      <Download size={14} /> {kind.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {job.status === 'completed' && (
              <div className="card p-5 sm:p-6">
                <div className="mb-4">
                  <p className="eyebrow">FIND A LYRIC MOMENT</p>
                  <p className="text-sm text-muted mt-2">Enter one lyric sentence. Matching ignores accents and tolerates transcription mistakes.</p>
                </div>
                <form onSubmit={searchLyrics} className="flex flex-col sm:flex-row gap-2">
                  <input
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setCandidates([]);
                      setSelected(null);
                      setHasSearched(false);
                    }}
                    placeholder="hạnh phúc anh xây sao em lại phủi tay"
                    className="input-field flex-1 min-w-0"
                  />
                  <button disabled={!query.trim() || searching} className="btn-primary px-4 py-2.5 disabled:opacity-40">
                    {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                    find timestamp
                  </button>
                </form>

                {!!candidates.length && (
                  <div className="mt-4 space-y-2">
                    {candidates.map((candidate, index) => (
                      <button
                        key={`${candidate.start}-${candidate.end}`}
                        type="button"
                        onClick={() => preview(candidate)}
                        className={`w-full text-left rounded-input border p-3 transition-colors ${selected === candidate ? 'border-brass bg-paper2' : 'border-rule hover:border-rule2'}`}
                      >
                        <span className="flex items-center justify-between gap-3">
                          <span className="font-mono text-xs text-brass tabular-nums">{timestamp(candidate.start)} → {timestamp(candidate.end)}</span>
                          <span className="readout">{Math.round(candidate.score * 100)}% MATCH {index === 0 ? '· BEST' : ''}</span>
                        </span>
                        <span className="flex items-start gap-2 mt-2 text-sm text-ink2">
                          <Play size={13} className="mt-0.5 shrink-0" /> {candidate.matched_text}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {!searching && hasSearched && candidates.length === 0 && (
                  <p className="text-sm text-muted mt-4">No close match found. Try a longer phrase or a spelling variant.</p>
                )}
                {previewing && <p className="readout mt-3">CREATING PREVIEW…</p>}
                {previewUrl && <audio key={previewUrl} controls autoPlay src={previewUrl} className="w-full mt-4" />}
              </div>
            )}

            {job.status === 'completed' && selected && (
              <div className="card p-5 sm:p-6">
                <div className="mb-4">
                  <p className="eyebrow">EXPORT MUSIC EXCERPT</p>
                  <p className="text-sm text-muted mt-2">Export a clean 10-second WAV that keeps the complete final matched word. You can join it to your clip manually.</p>
                </div>
                <div className="space-y-4">
                  <div className="rounded-input border border-rule bg-paper p-3">
                    <span className="readout block">10-SECOND WAV · FINAL WORD PROTECTED</span>
                    <span className="text-sm text-ink2 mt-2 block">
                      approximately {timestamp(Math.max(0, selected.end + 0.15 - 10))} → {timestamp(selected.end + 0.15)}
                    </span>
                    <span className="text-xs text-muted mt-1 block">Ends 150 ms after “{selected.matched_text}” so the last sound is not cut off.</span>
                  </div>
                  <button
                    onClick={exportExcerpt}
                    disabled={extracting}
                    className="btn-primary px-4 py-2.5 disabled:opacity-40"
                  >
                    {extracting ? <Loader2 size={15} className="animate-spin" /> : <Scissors size={15} />}
                    {extracting ? 'exporting' : 'export 10-second WAV'}
                  </button>
                </div>

                {excerptResult?.audio_url && (
                  <div className="mt-5 border-t border-rule pt-5">
                    <p className="eyebrow mb-3">EXCERPT READY</p>
                    <audio controls src={getApiUrl(excerptResult.audio_url)} className="w-full" />
                    <p className="text-xs text-muted mt-2">
                      Exact range: {timestamp(excerptResult.plan.excerpt.start)} → {timestamp(excerptResult.plan.excerpt.end)} · {excerptResult.plan.excerpt.duration.toFixed(2)}s
                    </p>
                    <button onClick={() => download(excerptResult.audio_url, 'lyric-excerpt-10s.wav')} className="btn-quiet px-3 py-2 text-xs mt-3">
                      <Download size={14} /> download WAV
                    </button>
                  </div>
                )}

                <div className="mt-6 border-t border-rule pt-5 space-y-4">
                  <div>
                    <p className="eyebrow">JOIN EXCERPT TO VIDEO</p>
                    <p className="text-sm text-muted mt-2">Uses the same final-word-safe range shown above, then starts the selected video.</p>
                  </div>
                  <div className="grid sm:grid-cols-2 gap-2">
                    {[
                      ['openshort', 'Existing OpenShort', 'Use a clip from the current OpenShorts job.'],
                      ['upload', 'Upload video manually', 'Use a video from outside OpenShorts.'],
                    ].map(([value, label, description]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => { setVideoSource(value); setJoinResult(null); setError(''); }}
                        className={`text-left rounded-input border p-3 ${videoSource === value ? 'border-brass bg-paper2' : 'border-rule'}`}
                      >
                        <span className="text-sm text-ink block">{label}</span>
                        <span className="text-xs text-muted mt-1 block">{description}</span>
                      </button>
                    ))}
                  </div>

                  {videoSource === 'openshort' && shortJobId && shortClips.length ? (
                    <label className="block">
                      <span className="readout block mb-2">TARGET SHORT</span>
                      <select value={clipIndex} onChange={(event) => setClipIndex(Number(event.target.value))} className="input-field w-full">
                        {shortClips.map((clip, index) => (
                          <option key={`${index}-${clip.video_url || ''}`} value={index}>
                            Short {index + 1} — {clip.video_title_for_youtube_short || clip.hook || 'Untitled clip'}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : videoSource === 'openshort' ? (
                    <p className="text-sm text-muted rounded-input border border-rule bg-paper p-4">
                      No Short is loaded. Create or reopen an OpenShorts job, or choose manual upload.
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <label className={`block border-2 border-dashed rounded-input p-5 text-center cursor-pointer transition-colors ${externalVideo ? 'border-brass' : 'border-rule2 hover:border-brass'}`}>
                        <input
                          type="file"
                          accept="video/mp4,video/quicktime,video/webm,.mkv"
                          className="hidden"
                          onChange={(event) => { setExternalVideo(event.target.files?.[0] || null); setJoinResult(null); }}
                        />
                        {externalVideo ? (
                          <span className="flex items-center justify-center gap-2 text-sm text-ink2 min-w-0">
                            <Film size={16} className="text-brass shrink-0" />
                            <span className="truncate">{externalVideo.name}</span>
                          </span>
                        ) : (
                          <span className="text-sm text-muted">Choose an external MP4, MOV, WebM or MKV video</span>
                        )}
                      </label>
                      <label className="flex items-start gap-3 text-sm text-muted cursor-pointer">
                        <input
                          type="checkbox"
                          checked={videoConfirmed}
                          onChange={(event) => setVideoConfirmed(event.target.checked)}
                          className="mt-0.5 accent-[var(--color-accent)]"
                        />
                        <span>I own this video or have permission to process it.</span>
                      </label>
                    </div>
                  )}

                  <div>
                    <span className="readout block mb-2">HOOK VISUAL</span>
                    <div className="grid sm:grid-cols-2 gap-2">
                      {[
                        ['pexels', 'Pexels timelapse', 'Search, cache and crop a portrait stock video.'],
                        ['hold_frame', 'Hold first frame', 'Use the original static intro visual.'],
                      ].map(([value, label, description]) => (
                        <button
                          key={value}
                          type="button"
                          onClick={() => { setHookVisual(value); setJoinResult(null); }}
                          className={`text-left rounded-input border p-3 ${hookVisual === value ? 'border-brass bg-paper2' : 'border-rule'}`}
                        >
                          <span className="text-sm text-ink block">{label}</span>
                          <span className="text-xs text-muted mt-1 block">{description}</span>
                        </button>
                      ))}
                    </div>
                    {hookVisual === 'pexels' && (
                      <div className="mt-3">
                        <input
                          value={visualQuery}
                          maxLength={120}
                          onChange={(event) => { setVisualQuery(event.target.value); setJoinResult(null); }}
                          placeholder="city timelapse"
                          className="input-field w-full"
                        />
                        <a href="https://www.pexels.com" target="_blank" rel="noopener noreferrer" className="text-xs text-brass hover:underline mt-2 inline-block">
                          Videos provided by Pexels
                        </a>
                      </div>
                    )}
                  </div>

                  <label className="flex items-start gap-3 rounded-input border border-rule bg-paper p-3 text-sm text-muted cursor-pointer">
                    <input
                      type="checkbox"
                      checked={lyricCaptions}
                      onChange={(event) => { setLyricCaptions(event.target.checked); setJoinResult(null); }}
                      className="mt-0.5 accent-[var(--color-accent)]"
                    />
                    <span>
                      <span className="text-ink2 block">Add lyric captions</span>
                      <span className="text-xs block mt-1">OpenShorts karaoke style · white Anton · yellow active word · intro only</span>
                    </span>
                  </label>

                  <button
                    onClick={joinToVideo}
                    disabled={joining || (videoSource === 'openshort' ? !(shortJobId && shortClips.length) : !(externalVideo && videoConfirmed))}
                    className="btn-primary px-4 py-2.5 disabled:opacity-40"
                  >
                    {joining ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                    {joining ? (videoSource === 'upload' ? 'uploading and joining' : 'joining') : 'join excerpt to video'}
                  </button>

                  {joinResult?.video_url && (
                    <div className="border-t border-rule pt-5">
                      <p className="eyebrow mb-3">VIDEO READY</p>
                      <video controls src={getApiUrl(joinResult.video_url)} className="w-full max-h-[34rem] rounded-input bg-black" />
                      <p className="text-xs text-muted mt-2">
                        Music range: {timestamp(joinResult.plan.render.lead_start)} → {timestamp(joinResult.plan.render.lead_end)} · final word + {Math.round(joinResult.plan.render.tail_padding * 1000)} ms
                      </p>
                      {joinResult.plan.hook_visual?.used === 'pexels' && (
                        <a
                          href={joinResult.plan.hook_visual.provider?.page_url || 'https://www.pexels.com'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-brass hover:underline mt-2 inline-block"
                        >
                          Video by {joinResult.plan.hook_visual.provider?.author || 'a Pexels creator'} on Pexels
                        </a>
                      )}
                      {joinResult.plan.hook_visual?.fallback_reason && (
                        <p className="badge-warn normal-case px-3 py-2 rounded-input mt-3 text-xs">
                          Pexels unavailable; used the first video frame. {joinResult.plan.hook_visual.fallback_reason}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-2 mt-3">
                        <button onClick={() => download(joinResult.video_url, 'video-with-lyric-excerpt.mp4')} className="btn-quiet px-3 py-2 text-xs">
                          <Download size={14} /> download MP4
                        </button>
                        {joinResult.plan.captions?.srt_url && (
                          <button onClick={() => download(joinResult.plan.captions.srt_url, 'lyric-intro.srt')} className="btn-quiet px-3 py-2 text-xs">
                            <Download size={14} /> SRT
                          </button>
                        )}
                        {joinResult.plan.captions?.ass_url && (
                          <button onClick={() => download(joinResult.plan.captions.ass_url, 'lyric-intro.ass')} className="btn-quiet px-3 py-2 text-xs">
                            <Download size={14} /> ASS
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {TERMINAL.has(job.status) && (
              <button onClick={reset} className="btn-ghost px-4 py-2 text-sm">
                <RotateCcw size={15} /> process another file
              </button>
            )}
          </div>
        )}

        {error && <div className="mt-4 badge-danger px-4 py-3 rounded-input text-sm normal-case">{error}</div>}
      </div>
    </div>
  );
}
