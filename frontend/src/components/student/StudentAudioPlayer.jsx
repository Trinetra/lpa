import React, { useEffect, useRef, useState } from "react";
import { studentApi } from "@/lib/api";
import { Play, Pause, Loader2 } from "lucide-react";

function fmtDuration(s) {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

// A plain <audio src> can't carry the student's bearer token, so this
// fetches via studentApi (same as StudentAuthImage does for photos) and
// plays from a blob URL instead.
export default function StudentAudioPlayer({ classId, durationSeconds, testid }) {
  const [src, setSrc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    return () => { if (src) URL.revokeObjectURL(src); };
  }, [src]);

  const ensureLoaded = async () => {
    if (src) return src;
    setLoading(true);
    try {
      const res = await studentApi.get(`/student/classes/${classId}/audio`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      setSrc(url);
      return url;
    } finally {
      setLoading(false);
    }
  };

  const toggle = async () => {
    if (playing) {
      audioRef.current?.pause();
      return;
    }
    await ensureLoaded();
    // audioRef only exists once `src` is set and the <audio> element has
    // rendered — play on the next tick once state has flushed.
    setTimeout(() => audioRef.current?.play(), 0);
  };

  return (
    <div className="flex items-center gap-2" data-testid={testid}>
      {src && (
        <audio ref={audioRef} src={src} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
      )}
      <button type="button" onClick={toggle} disabled={loading} className="btn-ghost p-1.5" data-testid={testid ? `${testid}-btn` : undefined}>
        {loading ? <Loader2 size={12} className="animate-spin" /> : playing ? <Pause size={12} /> : <Play size={12} />}
      </button>
      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
        Voice note{durationSeconds ? ` · ${fmtDuration(durationSeconds)}` : ""}
      </span>
    </div>
  );
}
