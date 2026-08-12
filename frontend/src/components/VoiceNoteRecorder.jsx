import React, { useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { Mic, Square, Play, Pause, Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";

// Browsers pick their own native MediaRecorder codec (WebM/Opus on
// Chrome/Firefox/Edge, MP4/AAC on Safari) — both are compact and
// well-suited for voice, so no format is forced here.
function pickMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const c of candidates) {
    if (window.MediaRecorder?.isTypeSupported?.(c)) return c;
  }
  return "";
}

function fmtDuration(s) {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/**
 * Records a single voice note via the browser mic. If `classId` is set,
 * uploads immediately on stop (editing an existing class). If not, holds
 * the recording as a local blob and calls `onLocalBlob` — the parent
 * uploads it itself once the class actually exists (the "Log a class" form,
 * where there's no class id yet at record time).
 */
export default function VoiceNoteRecorder({ classId, existing, onChanged, onLocalBlob }) {
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [localBlob, setLocalBlob] = useState(null);
  const [localUrl, setLocalUrl] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const startRef = useRef(null);
  const timerRef = useRef(null);
  const audioRef = useRef(null);

  useEffect(() => {
    return () => {
      if (localUrl) URL.revokeObjectURL(localUrl);
      clearInterval(timerRef.current);
    };
  }, [localUrl]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        clearInterval(timerRef.current);
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        const duration = (Date.now() - startRef.current) / 1000;
        if (classId) {
          await upload(blob, duration);
        } else {
          setLocalBlob(blob);
          setLocalUrl(URL.createObjectURL(blob));
          onLocalBlob?.(blob, duration);
        }
      };
      mediaRecorderRef.current = recorder;
      startRef.current = Date.now();
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((Date.now() - startRef.current) / 1000), 200);
      recorder.start();
      setRecording(true);
    } catch (e) {
      toast.error("Couldn't access the microphone — check your browser's permission for this site");
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  const upload = async (blob, duration) => {
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", blob, `note.${blob.type.includes("mp4") ? "m4a" : "webm"}`);
      body.append("duration_seconds", String(duration));
      const { data } = await api.post(`/classes/${classId}/audio`, body, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      onChanged?.(data);
      toast.success("Voice note saved");
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't save the recording");
    } finally {
      setUploading(false);
    }
  };

  const removeExisting = async () => {
    setUploading(true);
    try {
      const { data } = await api.delete(`/classes/${classId}/audio`);
      onChanged?.(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't remove the recording");
    } finally {
      setUploading(false);
    }
  };

  const removeLocal = () => {
    if (localUrl) URL.revokeObjectURL(localUrl);
    setLocalBlob(null);
    setLocalUrl(null);
    onLocalBlob?.(null, null);
  };

  const togglePlay = () => {
    if (!audioRef.current) return;
    if (playing) audioRef.current.pause();
    else audioRef.current.play();
  };

  const hasExisting = !!existing?.has_audio;
  const audioSrc = classId ? `${api.defaults.baseURL}/classes/${classId}/audio` : null;

  if (recording) {
    return (
      <div className="flex items-center gap-3" data-testid="voice-note-recording">
        <button type="button" onClick={stopRecording} className="btn-pill flex items-center gap-2 text-xs"
          style={{ background: "var(--error)" }} data-testid="voice-note-stop-btn">
          <Square size={12} /> Stop
        </button>
        <span className="text-xs flex items-center gap-1.5" style={{ color: "var(--error)" }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--error)", display: "inline-block" }} className="animate-pulse" />
          Recording {fmtDuration(elapsed)}
        </span>
      </div>
    );
  }

  if (localBlob) {
    return (
      <div className="flex items-center gap-3" data-testid="voice-note-local-preview">
        <audio ref={audioRef} src={localUrl} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
        <button type="button" onClick={togglePlay} className="btn-ghost p-2" data-testid="voice-note-preview-play">
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>Voice note recorded — will save with this class</span>
        <button type="button" onClick={removeLocal} className="btn-ghost p-2" style={{ color: "var(--error)" }} data-testid="voice-note-discard-local">
          <Trash2 size={14} />
        </button>
      </div>
    );
  }

  if (hasExisting) {
    return (
      <div className="flex items-center gap-3" data-testid="voice-note-existing">
        <audio ref={audioRef} src={audioSrc} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
        <button type="button" onClick={togglePlay} className="btn-ghost p-2" data-testid="voice-note-play">
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Voice note{existing?.audio_duration_seconds ? ` · ${fmtDuration(existing.audio_duration_seconds)}` : ""}
        </span>
        <button type="button" onClick={startRecording} disabled={uploading} className="btn-ghost text-xs" data-testid="voice-note-rerecord-btn">
          Re-record
        </button>
        <button type="button" onClick={removeExisting} disabled={uploading} className="btn-ghost p-2" style={{ color: "var(--error)" }} data-testid="voice-note-delete-btn">
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
        </button>
      </div>
    );
  }

  return (
    <button type="button" onClick={startRecording} disabled={uploading} data-testid="voice-note-record-btn"
      className="btn-ghost flex items-center gap-2 text-xs">
      {uploading ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />} Record voice note
    </button>
  );
}
