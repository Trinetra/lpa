import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { uploadLibraryFile } from "@/lib/libraryUpload";
import { fmtSize } from "@/pages/LibraryPage";
import { toast } from "sonner";
import {
  ArrowLeft, Upload, Link2, X, Download, Trash2, RotateCcw, Music, Film, FileText, Image as ImageIcon, ExternalLink, File as FileIcon,
} from "lucide-react";

// One production's Library: material filed by category and by performance
// (a tour stop, a one-off performance, or a venue added here), or "General".
export const CATEGORIES = [
  ["concept", "Concept"], ["music", "Music"], ["lighting", "Lighting"], ["video", "Video"], ["photos", "Photos"], ["costume", "Costume"],
  ["set", "Set & props"], ["choreography", "Choreography notes"], ["expenses", "Expenses"], ["contracts", "Contracts"],
  ["press", "Press"], ["publicity", "Posters & publicity"], ["other", "Other"],
];
const categoryLabel = Object.fromEntries(CATEGORIES);
const inputCls = "w-full bg-transparent border border-white/10 rounded px-3 py-2 text-sm";
const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");
export const perfText = (p) => (p ? [p.venue, p.city, fmtDate(p.date)].filter(Boolean).join(" · ") || p.label || "Performance" : "General");

const guessCategory = (file) => {
  const t = file.type || "";
  if (t.startsWith("audio/")) return "music";
  if (t.startsWith("video/")) return "video";
  if (t.startsWith("image/") || /\.(heic|heif)$/i.test(file.name)) return "photos";
  return "other";
};

function ItemIcon({ item, size = 28 }) {
  const t = item.content_type || "";
  const Icon = item.kind === "link" ? Link2 : t.startsWith("audio/") ? Music : t.startsWith("video/") ? Film
    : t.startsWith("image/") ? ImageIcon : t === "application/pdf" ? FileText : FileIcon;
  return <Icon size={size} style={{ color: "var(--text-muted)" }} />;
}

function Field({ label, children }) {
  return (
    <label className="block space-y-1">
      <span className="uppercase-label">{label}</span>
      {children}
    </label>
  );
}

// Performance dropdown with "+ New performance…" for shows that never went
// through Tours (older works, one-off venues).
function PerformanceSelect({ productionId, performances, value, onChange, onAdded }) {
  const [adding, setAdding] = useState(false);
  const [venue, setVenue] = useState("");
  const [city, setCity] = useState("");
  const [date, setDate] = useState("");
  const [saving, setSaving] = useState(false);

  const add = async () => {
    if (!venue.trim()) return toast.error("Venue is required");
    setSaving(true);
    try {
      const r = await api.post(`/library/productions/${productionId}/venues`, { venue, city: city || null, date: date || null });
      onAdded(r.data);
      onChange(r.data.ref);
      setAdding(false); setVenue(""); setCity(""); setDate("");
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't add that performance");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <select className={inputCls} value={value || ""} data-testid="library-performance-select"
        onChange={(e) => (e.target.value === "__new" ? setAdding(true) : onChange(e.target.value))}>
        <option value="">General — not tied to a venue</option>
        {performances.map((p) => (
          <option key={p.ref} value={p.ref}>{perfText(p)}{p.label ? ` (${p.label})` : ""}</option>
        ))}
        <option value="__new">+ New performance…</option>
      </select>
      {adding && (
        <div className="surface p-3 space-y-2">
          <input className={inputCls} placeholder="Venue (required)" value={venue} onChange={(e) => setVenue(e.target.value)} data-testid="new-venue-input" />
          <div className="grid grid-cols-2 gap-2">
            <input className={inputCls} placeholder="City" value={city} onChange={(e) => setCity(e.target.value)} />
            <input className={inputCls} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost text-xs" onClick={() => setAdding(false)}>Cancel</button>
            <button type="button" className="btn-pill text-xs" onClick={add} disabled={saving} data-testid="new-venue-save">{saving ? "Adding…" : "Add"}</button>
          </div>
        </div>
      )}
    </div>
  );
}

// The fields every upload/link/edit shares.
function MetaFields({ meta, setMeta, productionId, performances, onPerformanceAdded }) {
  const set = (k, v) => setMeta({ ...meta, [k]: v });
  return (
    <>
      <Field label="Category">
        <select className={inputCls} value={meta.category} onChange={(e) => set("category", e.target.value)} data-testid="library-category-select">
          {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </Field>
      <Field label="Performance">
        <PerformanceSelect productionId={productionId} performances={performances} value={meta.performance_ref}
          onChange={(v) => set("performance_ref", v)} onAdded={onPerformanceAdded} />
      </Field>
      <Field label="Version (optional)">
        <input className={inputCls} value={meta.version || ""} placeholder="e.g. Final, v2 after tech" onChange={(e) => set("version", e.target.value)} />
      </Field>
      <Field label="Notes (optional)">
        <textarea className={inputCls} rows={2} value={meta.notes || ""} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      <Field label="Tags (optional, comma separated)">
        <input className={inputCls} value={meta.tagsText || ""} placeholder="e.g. Act 2, Rāvaṇa solo" onChange={(e) => set("tagsText", e.target.value)} />
      </Field>
    </>
  );
}

const metaPayload = ({ tagsText, ...m }) => ({
  ...m, performance_ref: m.performance_ref || null,
  tags: (tagsText || "").split(",").map((t) => t.trim()).filter(Boolean),
});

function Modal({ title, onClose, children, testid }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="surface w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto space-y-4" data-testid={testid}>
        <div className="flex items-center justify-between">
          <h3 className="font-serif-display text-2xl">{title}</h3>
          {onClose && <button type="button" onClick={onClose} className="p-1"><X size={18} /></button>}
        </div>
        {children}
      </div>
    </div>
  );
}

function UploadPanel({ productionId, performances, initialFiles, defaultPerformance, onPerformanceAdded, onClose, onUploaded }) {
  const [files, setFiles] = useState(initialFiles);
  const [meta, setMeta] = useState({ category: guessCategory(initialFiles[0]), performance_ref: defaultPerformance || "" });
  const [progress, setProgress] = useState({}); // index -> bytes | "done" | "failed"
  const [running, setRunning] = useState(false);
  const abortRef = useRef(null);
  const addRef = useRef(null);

  useEffect(() => {
    if (!running) return;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [running]);

  const start = async () => {
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const pending = files.map((_, i) => i).filter((i) => progress[i] !== "done");
    let ok = 0;
    for (const i of pending) {
      if (controller.signal.aborted) break;
      try {
        await uploadLibraryFile(productionId, files[i], metaPayload(meta), {
          signal: controller.signal, onProgress: (b) => setProgress((p) => ({ ...p, [i]: b })),
        });
        setProgress((p) => ({ ...p, [i]: "done" }));
        ok++;
      } catch (e) {
        setProgress((p) => ({ ...p, [i]: "failed" }));
        if (e.name !== "AbortError") toast.error(`${files[i].name}: ${formatApiErrorDetail(e?.response?.data?.detail) || e.message || "upload failed"}`);
      }
    }
    setRunning(false);
    if (ok) onUploaded();
    if (ok === pending.length) {
      toast.success(`Uploaded ${ok} file${ok === 1 ? "" : "s"}`);
      onClose();
    }
  };

  const total = files.reduce((s, f) => s + f.size, 0);
  return (
    <Modal title="Upload to Library" onClose={running ? null : onClose} testid="library-upload-panel">
      <div className="space-y-2">
        {files.map((f, i) => {
          const p = progress[i];
          const pct = p === "done" ? 100 : typeof p === "number" ? Math.min(100, Math.round((p / f.size) * 100)) : 0;
          return (
            <div key={i} className="text-sm">
              <div className="flex justify-between gap-2">
                <span className="truncate">{f.name}</span>
                <span className="shrink-0 flex items-center gap-2" style={{ color: p === "failed" ? "var(--error)" : "var(--text-muted)" }}>
                  {p === "failed" ? "Failed" : p === "done" ? "Done" : typeof p === "number" ? `${pct}%` : fmtSize(f.size)}
                  {!running && !p && (
                    <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))} title="Remove"><X size={13} /></button>
                  )}
                </span>
              </div>
              {(running || p) && (
                <div className="h-1 rounded mt-1" style={{ background: "var(--border)" }}>
                  <div className="h-1 rounded" style={{ width: `${pct}%`, background: p === "failed" ? "var(--error)" : "var(--primary)" }} />
                </div>
              )}
            </div>
          );
        })}
        {!running && (
          <>
            <input ref={addRef} type="file" multiple hidden onChange={(e) => { setFiles([...files, ...e.target.files]); e.target.value = ""; }} />
            <button type="button" className="btn-ghost text-xs" onClick={() => addRef.current?.click()}>+ Add more files</button>
          </>
        )}
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{files.length} file{files.length === 1 ? "" : "s"} · {fmtSize(total)} — the details below apply to all of them.</div>
      </div>
      <fieldset disabled={running} className="space-y-4">
        <MetaFields meta={meta} setMeta={setMeta} productionId={productionId} performances={performances} onPerformanceAdded={onPerformanceAdded} />
      </fieldset>
      <div className="flex justify-end gap-3">
        {running
          ? <button type="button" className="btn-ghost" onClick={() => abortRef.current?.abort()}>Cancel upload</button>
          : <button type="button" className="btn-ghost" onClick={onClose}>Close</button>}
        {!running && (
          <button type="button" className="btn-pill" disabled={!files.length} onClick={start} data-testid="library-upload-start">
            {Object.values(progress).includes("failed") ? "Retry failed" : "Upload"}
          </button>
        )}
      </div>
      {running && <p className="text-xs" style={{ color: "var(--text-muted)" }}>Keep this tab open until it finishes — you can use other apps meanwhile.</p>}
    </Modal>
  );
}

function LinkPanel({ productionId, performances, defaultPerformance, onPerformanceAdded, onClose, onSaved }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [meta, setMeta] = useState({ category: "video", performance_ref: defaultPerformance || "" });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await api.post(`/library/productions/${productionId}/links`, { url, title: title || null, ...metaPayload(meta) });
      toast.success("Link added");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't add that link");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title="Add a link" onClose={onClose} testid="library-link-panel">
      <Field label="Link"><input className={inputCls} value={url} placeholder="YouTube, Vimeo, Google Drive…" onChange={(e) => setUrl(e.target.value)} /></Field>
      <Field label="Title (optional)"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      <MetaFields meta={meta} setMeta={setMeta} productionId={productionId} performances={performances} onPerformanceAdded={onPerformanceAdded} />
      <div className="flex justify-end gap-3">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="button" className="btn-pill" disabled={!url.trim() || saving} onClick={save}>{saving ? "Adding…" : "Add link"}</button>
      </div>
    </Modal>
  );
}

function Preview({ item }) {
  const [url, setUrl] = useState(null);
  const t = item.content_type || "";
  const heic = /\.(heic|heif)$/i.test(item.filename || "");
  useEffect(() => {
    setUrl(null);
    if (item.kind === "file" && !heic && /^(image|video|audio)\/|^application\/pdf$/.test(t)) {
      api.get(`/library/items/${item.id}/url`).then((r) => setUrl(r.data.url)).catch(() => {});
    }
  }, [item.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (item.kind === "link") {
    return <a href={item.url} target="_blank" rel="noopener noreferrer" className="btn-ghost text-sm inline-flex items-center gap-2"><ExternalLink size={14} /> Open link</a>;
  }
  if (heic && item.thumb_url) return <img src={item.thumb_url} alt="" className="w-full rounded" />;
  if (!url) return item.thumb_url ? <img src={item.thumb_url} alt="" className="w-full rounded" /> : null;
  if (t.startsWith("image/")) return <img src={url} alt="" className="w-full rounded" />;
  if (t.startsWith("video/")) return <video src={url} controls playsInline poster={item.thumb_url || undefined} className="w-full rounded" style={{ background: "#000" }} />;
  if (t.startsWith("audio/")) return <audio src={url} controls className="w-full" />;
  return <iframe src={url} title={item.title} className="w-full rounded" style={{ height: 420, background: "#fff" }} />;
}

function ItemPanel({ item, productionId, performances, onPerformanceAdded, onClose, onChanged, inTrash }) {
  const [meta, setMeta] = useState({
    title: item.title, category: item.category, performance_ref: item.performance?.ref || "",
    version: item.version, notes: item.notes, tagsText: (item.tags || []).join(", "),
  });
  const [saving, setSaving] = useState(false);
  const initial = useRef(JSON.stringify(meta));
  const dirty = JSON.stringify(meta) !== initial.current;
  // A stop/venue no longer offered (deleted tour stop) stays shown as it was saved.
  const perfs = item.performance && !performances.some((p) => p.ref === item.performance.ref) ? [item.performance, ...performances] : performances;

  const act = async (fn, msg) => {
    setSaving(true);
    try {
      await fn();
      if (msg) toast.success(msg);
      onChanged();
      return true;
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "That didn't work");
      return false;
    } finally {
      setSaving(false);
    }
  };
  const save = () => act(async () => {
    const { performance_ref, ...rest } = metaPayload(meta);
    const body = { ...rest, title: meta.title || "" };
    if (performance_ref !== (item.performance?.ref || null)) body.performance_ref = performance_ref || "";
    await api.patch(`/library/items/${item.id}`, body);
    initial.current = JSON.stringify(meta);
  }, "Saved");
  const download = async () => {
    try {
      const r = await api.get(`/library/items/${item.id}/url`, { params: { download: true } });
      window.location.href = r.data.url;
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't download");
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end" style={{ background: "rgba(0,0,0,0.5)" }} onClick={onClose}>
      <aside className="surface h-full w-full max-w-md p-6 overflow-y-auto space-y-4" style={{ borderRadius: 0 }} onClick={(e) => e.stopPropagation()} data-testid="library-item-panel">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="uppercase-label">{categoryLabel[item.category]}</div>
            <h3 className="font-serif-display text-2xl break-words">{item.title}</h3>
            {item.kind === "file" && <div className="text-xs break-all" style={{ color: "var(--text-muted)" }}>{item.filename} · {fmtSize(item.size)}</div>}
          </div>
          <button type="button" onClick={onClose} className="p-1 shrink-0"><X size={18} /></button>
        </div>

        <Preview item={item} />

        <div className="flex flex-wrap gap-2">
          {item.kind === "file" && <button type="button" className="btn-ghost text-xs flex items-center gap-1" onClick={download} data-testid="library-download"><Download size={13} /> Download</button>}
          {inTrash ? (
            <>
              <button type="button" className="btn-ghost text-xs flex items-center gap-1" disabled={saving}
                onClick={() => act(() => api.post(`/library/items/${item.id}/restore`), "Restored").then((ok) => ok && onClose())}><RotateCcw size={13} /> Restore</button>
              <button type="button" className="btn-ghost text-xs flex items-center gap-1" style={{ color: "var(--error)" }} disabled={saving}
                onClick={() => window.confirm(`Delete "${item.title}" for good? This can't be undone.`) && act(() => api.delete(`/library/items/${item.id}`), "Deleted").then((ok) => ok && onClose())}>
                <Trash2 size={13} /> Delete for good</button>
            </>
          ) : (
            <button type="button" className="btn-ghost text-xs flex items-center gap-1" style={{ color: "var(--error)" }} disabled={saving} data-testid="library-trash"
              onClick={() => act(() => api.delete(`/library/items/${item.id}`), "Moved to Trash").then((ok) => ok && onClose())}><Trash2 size={13} /> Move to Trash</button>
          )}
        </div>

        {!inTrash && (
          <div className="space-y-4 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            <Field label="Title"><input className={inputCls} value={meta.title || ""} onChange={(e) => setMeta({ ...meta, title: e.target.value })} /></Field>
            <MetaFields meta={meta} setMeta={setMeta} productionId={productionId} performances={perfs} onPerformanceAdded={onPerformanceAdded} />
            <button type="button" className="btn-pill" disabled={!dirty || saving} onClick={save} data-testid="library-item-save">{saving ? "Saving…" : "Save changes"}</button>
          </div>
        )}
      </aside>
    </div>
  );
}

export default function LibraryProductionPage() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [trash, setTrash] = useState(false);
  const [perfFilter, setPerfFilter] = useState("all"); // "all" | "general" | ref
  const [selected, setSelected] = useState(null);
  const [uploadFiles, setUploadFiles] = useState(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef(null);

  const load = () => api.get(`/library/productions/${id}`, { params: { trash } }).then((r) => setData(r.data))
    .catch((e) => { toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't load"); setData((d) => d || { error: true }); });
  useEffect(() => { load(); }, [id, trash]); // eslint-disable-line react-hooks/exhaustive-deps

  if (data === null) return <div className="uppercase-label">Loading…</div>;
  if (data.error) return <Link to="/library" className="btn-ghost text-xs inline-flex items-center gap-1"><ArrowLeft size={13} /> Library</Link>;

  const { production, performances, items } = data;
  const addPerformance = (p) => setData((d) => ({ ...d, performances: [p, ...d.performances].sort((a, b) => (b.date || "").localeCompare(a.date || "")) }));
  const shown = items.filter((it) => perfFilter === "all" || (perfFilter === "general" ? !it.performance : it.performance?.ref === perfFilter));
  // Only tabs for performances that have material, plus the selected one.
  const usedRefs = new Set(items.map((it) => it.performance?.ref).filter(Boolean));
  const tabs = [["all", "All"], ...(items.some((it) => !it.performance) ? [["general", "General"]] : []),
    ...performances.filter((p) => usedRefs.has(p.ref) || p.ref === perfFilter).map((p) => [p.ref, perfText(p)])];
  const defaultPerformance = perfFilter !== "all" && perfFilter !== "general" ? perfFilter : "";

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (!trash && e.dataTransfer.files?.length) setUploadFiles([...e.dataTransfer.files]);
  };

  return (
    <div data-testid="library-production-page" className="space-y-6 min-h-[60vh]"
      onDragOver={(e) => { e.preventDefault(); if (!trash) setDragging(true); }} onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }} onDrop={onDrop}
      style={dragging ? { outline: "2px dashed var(--primary)", outlineOffset: 8, borderRadius: 8 } : undefined}>
      <Link to="/library" className="btn-ghost text-xs inline-flex items-center gap-1"><ArrowLeft size={13} /> Library</Link>

      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">{production.year}{trash ? " · Trash" : ""}</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">{production.title}</h1>
          {production.subtitle && <div className="italic mt-1" style={{ color: "var(--text-muted)" }}>{production.subtitle}</div>}
        </div>
        <div className="flex gap-2 flex-wrap">
          {!trash && (
            <>
              <input ref={fileRef} type="file" multiple hidden onChange={(e) => { if (e.target.files.length) setUploadFiles([...e.target.files]); e.target.value = ""; }} />
              <button type="button" className="btn-pill flex items-center gap-2" onClick={() => fileRef.current?.click()} data-testid="library-upload-btn"><Upload size={16} /> Upload</button>
              <button type="button" className="btn-ghost flex items-center gap-2" onClick={() => setLinkOpen(true)} data-testid="library-link-btn"><Link2 size={16} /> Add link</button>
            </>
          )}
          <button type="button" className="btn-ghost text-sm flex items-center gap-1" onClick={() => { setTrash(!trash); setPerfFilter("all"); }} data-testid="library-trash-toggle">
            {trash ? <><ArrowLeft size={14} /> Back to files</> : <><Trash2 size={14} /> Trash</>}
          </button>
        </div>
      </header>

      {tabs.length > 2 && (
        <div className="flex gap-1 overflow-x-auto" style={{ borderBottom: "1px solid var(--border)" }}>
          {tabs.map(([k, label]) => (
            <button key={k} type="button" onClick={() => setPerfFilter(k)} className="px-3 py-2 text-sm whitespace-nowrap"
              style={{ borderBottom: perfFilter === k ? "2px solid var(--primary)" : "2px solid transparent", color: perfFilter === k ? "var(--text)" : "var(--text-muted)" }}>
              {label}
            </button>
          ))}
        </div>
      )}

      {shown.length === 0 && (
        <div className="surface p-8 text-center" style={{ color: "var(--text-muted)" }}>
          {trash ? "Trash is empty." : "Nothing here yet — drag files onto this page, or use Upload."}
        </div>
      )}

      {CATEGORIES.filter(([k]) => shown.some((it) => it.category === k)).map(([k, label]) => (
        <section key={k} className="space-y-3">
          <div className="uppercase-label">{label}</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {shown.filter((it) => it.category === k).map((it) => (
              <button key={it.id} type="button" onClick={() => setSelected(it)} className="surface surface-hover text-left overflow-hidden" data-testid={`library-item-${it.id}`}>
                <div className="flex items-center justify-center" style={{ aspectRatio: "4 / 3", background: "var(--border)" }}>
                  {it.thumb_url ? <img src={it.thumb_url} alt="" className="w-full h-full object-cover" loading="lazy" /> : <ItemIcon item={it} />}
                </div>
                <div className="p-3 space-y-0.5">
                  <div className="text-sm truncate">{it.title}</div>
                  <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                    {[perfFilter === "all" ? perfText(it.performance) : null, it.version].filter(Boolean).join(" · ") || " "}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </section>
      ))}

      {uploadFiles && (
        <UploadPanel productionId={id} performances={performances} initialFiles={uploadFiles} defaultPerformance={defaultPerformance}
          onPerformanceAdded={addPerformance} onClose={() => setUploadFiles(null)} onUploaded={load} />
      )}
      {linkOpen && (
        <LinkPanel productionId={id} performances={performances} defaultPerformance={defaultPerformance}
          onPerformanceAdded={addPerformance} onClose={() => setLinkOpen(false)} onSaved={load} />
      )}
      {selected && (
        <ItemPanel key={selected.id} item={selected} productionId={id} performances={performances} inTrash={trash}
          onPerformanceAdded={addPerformance} onClose={() => setSelected(null)}
          onChanged={load} />
      )}
    </div>
  );
}
