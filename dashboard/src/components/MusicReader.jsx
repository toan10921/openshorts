import React, { useEffect, useRef, useState } from 'react';
import { Download, FileAudio, Loader2, Music2, RotateCcw, Upload, X } from 'lucide-react';
import { apiFetch, apiJson } from '../lib/api';

const TERMINAL = new Set(['completed', 'failed']);

const errorText = (error, fallback) => error?.detail || error?.message || fallback;

export default function MusicReader() {
  const [file, setFile] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState(null);
  const [lyrics, setLyrics] = useState(null);
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState(false);
  const pollTimer = useRef(null);

  useEffect(() => () => clearTimeout(pollTimer.current), []);

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

  const reset = () => {
    clearTimeout(pollTimer.current);
    setFile(null);
    setConfirmed(false);
    setJob(null);
    setLyrics(null);
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
