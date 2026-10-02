import React, { useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { ArrowUp, ArrowDown, Trash2, Plus, ExternalLink, Upload } from "lucide-react";

// Edits the Works, Watch and Gallery sections of www.pravaahacfm.com. Each tab
// edits a local copy and saves the whole list; the backend re-renders that
// section of the static site immediately.
const SITE = "https://www.pravaahacfm.com";
const inputCls = "w-full bg-transparent border border-white/10 rounded px-3 py-2 text-sm";
const ytLink = (id) => (id ? `https://youtu.be/${id}` : "");

const move = (list, i, d) => {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
};

function RowControls({ i, count, onMove, onRemove, testid }) {
  return (
    <div className="flex gap-1 shrink-0">
      <button type="button" className="btn-ghost p-2" onClick={() => onMove(i, -1)} disabled={i === 0} title="Move up"
        data-testid={`${testid}-up-${i}`}><ArrowUp size={14} /></button>
      <button type="button" className="btn-ghost p-2" onClick={() => onMove(i, 1)} disabled={i === count - 1} title="Move down"
        data-testid={`${testid}-down-${i}`}><ArrowDown size={14} /></button>
      <button type="button" className="btn-ghost p-2" style={{ color: "var(--error)" }} onClick={() => onRemove(i)} title="Remove"
        data-testid={`${testid}-remove-${i}`}><Trash2 size={14} /></button>
    </div>
  );
}

// Label above, optional one-line hint below — placeholders alone vanish once
// she starts typing, which left the video fields unexplained on her phone.
function Field({ label, hint, children, className = "" }) {
  return (
    <label className={`block space-y-1 ${className}`}>
      <span className="uppercase-label">{label}</span>
      {children}
      {hint && <span className="block text-xs" style={{ color: "var(--text-muted)" }}>{hint}</span>}
    </label>
  );
}

const LINK_HINT = "On YouTube, tap Share → Copy link, then paste it here.";
const PHOTO_DESC_HINT = "Optional. Not shown on the website — it's read by Google and by screen readers for blind visitors.";

function SaveBar({ dirty, saving, onSave, testid }) {
  return (
    <div className="flex items-center gap-3">
      <button type="button" className="btn-pill" onClick={onSave} disabled={!dirty || saving} data-testid={testid}>
        {saving ? "Saving…" : "Save to website"}
      </button>
      {dirty && <span className="text-xs" style={{ color: "var(--text-muted)" }}>Unsaved changes</span>}
    </div>
  );
}

function useSaver(endpoint, toPayload, onSaved) {
  const [saving, setSaving] = useState(false);
  const save = async (list) => {
    setSaving(true);
    try {
      const r = await api.put(endpoint, toPayload(list));
      onSaved(r.data);
      toast.success("Website updated");
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Couldn't save");
    } finally {
      setSaving(false);
    }
  };
  return [saving, save];
}

function ProductionsTab({ initial, onSaved }) {
  const [list, setList] = useState(() => initial.map((p) => ({ ...p, video: ytLink(p.video_id) })));
  const [dirty, setDirty] = useState(false);
  const update = (next) => { setList(next); setDirty(true); };
  const set = (i, k, v) => update(list.map((p, j) => (j === i ? { ...p, [k]: v } : p)));
  const [saving, save] = useSaver(
    "/website/productions",
    (l) => l.map(({ year, title, subtitle, description, video, video_label }) => ({ year: year || "", title, subtitle, description, video, video_label })),
    (data) => { onSaved(data); setDirty(false); },
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <button type="button" className="btn-ghost text-sm flex items-center gap-1" data-testid="add-production"
          onClick={() => update([{ year: String(new Date().getFullYear()), title: "", subtitle: "", description: "", video: "", video_label: "" }, ...list])}>
          <Plus size={14} /> Add production
        </button>
        <SaveBar dirty={dirty} saving={saving} onSave={() => save(list)} testid="save-productions" />
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>Shown on the website in this order — newest first.</p>
      <div className="surface">
        {list.map((p, i) => (
          <div key={i} className="px-4 sm:px-6 py-5 space-y-3" style={{ borderTop: i ? "1px solid var(--border)" : "none" }} data-testid={`production-${i}`}>
            <div className="flex justify-between items-center gap-2">
              <span className="font-serif-display text-lg truncate">{p.title || "New production"}</span>
              <RowControls i={i} count={list.length} testid="production" onMove={(a, d) => update(move(list, a, d))}
                onRemove={(a) => window.confirm(`Remove "${list[a].title || "this production"}"?`) && update(list.filter((_, j) => j !== a))} />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-[110px_1fr] gap-3">
              <Field label="Year"><input className={inputCls} value={p.year || ""} placeholder="2026" onChange={(e) => set(i, "year", e.target.value)} /></Field>
              <Field label="Title"><input className={inputCls} value={p.title || ""} placeholder="e.g. Rāvaṇa" onChange={(e) => set(i, "title", e.target.value)} /></Field>
            </div>
            <Field label="Subtitle" hint="Optional — shown after the title, e.g. “the dot that moved”.">
              <input className={inputCls} value={p.subtitle || ""} onChange={(e) => set(i, "subtitle", e.target.value)} />
            </Field>
            <Field label="Description" hint="Optional — one or two sentences.">
              <textarea className={inputCls} rows={2} value={p.description || ""} onChange={(e) => set(i, "description", e.target.value)} />
            </Field>
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_180px] gap-3">
              <Field label="YouTube link" hint={`Optional. ${LINK_HINT}`}>
                <input className={inputCls} value={p.video || ""} placeholder="https://youtu.be/…" onChange={(e) => set(i, "video", e.target.value)} />
              </Field>
              <Field label="Link text" hint="Default: Watch excerpt">
                <input className={inputCls} value={p.video_label || ""} placeholder="Watch excerpt" onChange={(e) => set(i, "video_label", e.target.value)} />
              </Field>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function VideosTab({ initial, onSaved }) {
  const [list, setList] = useState(() => initial.map((v) => ({ video: ytLink(v.video_id), title: v.title })));
  const [dirty, setDirty] = useState(false);
  const update = (next) => { setList(next); setDirty(true); };
  const set = (i, k, v) => update(list.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const [saving, save] = useSaver("/website/videos", (l) => l, (data) => { onSaved(data); setDirty(false); });
  const thumb = (v) => {
    const m = (v || "").match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([A-Za-z0-9_-]{11})|^([A-Za-z0-9_-]{11})$/);
    const id = m && (m[1] || m[2]);
    return id ? `https://i.ytimg.com/vi/${id}/mqdefault.jpg` : null;
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <button type="button" className="btn-ghost text-sm flex items-center gap-1" data-testid="add-video"
          onClick={() => update([{ video: "", title: "" }, ...list])}>
          <Plus size={14} /> Add video
        </button>
        <SaveBar dirty={dirty} saving={saving} onSave={() => save(list)} testid="save-videos" />
      </div>
      <div className="surface">
        {list.map((v, i) => (
          <div key={i} className="px-4 sm:px-6 py-5 space-y-3" style={{ borderTop: i ? "1px solid var(--border)" : "none" }} data-testid={`video-${i}`}>
            <div className="flex justify-between items-center gap-3">
              <div className="shrink-0 rounded overflow-hidden" style={{ width: 128, height: 72, background: "#000" }}>
                {thumb(v.video) && <img src={thumb(v.video)} alt="" style={{ width: 128, height: 72, objectFit: "cover" }} />}
              </div>
              <RowControls i={i} count={list.length} testid="video" onMove={(a, d) => update(move(list, a, d))}
                onRemove={(a) => update(list.filter((_, j) => j !== a))} />
            </div>
            <Field label="YouTube link" hint={LINK_HINT}>
              <input className={inputCls} value={v.video} placeholder="https://youtu.be/…" onChange={(e) => set(i, "video", e.target.value)} />
            </Field>
            <Field label="Title" hint="Shown under the video on the website, e.g. “Rāvaṇa — the dot that moved”.">
              <input className={inputCls} value={v.title} onChange={(e) => set(i, "title", e.target.value)} />
            </Field>
          </div>
        ))}
      </div>
    </div>
  );
}

function GalleryTab({ initial, onSaved }) {
  const [list, setList] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const [uploading, setUploading] = useState(0);
  const fileRef = useRef(null);
  const update = (next) => { setList(next); setDirty(true); };
  const [saving, save] = useSaver("/website/gallery", (l) => l, (data) => { onSaved(data); setList(data.gallery); setDirty(false); });

  const upload = async (files) => {
    if (dirty && !window.confirm("Uploading saves the gallery — your unsaved reordering/edits will be saved too. Continue?")) return;
    if (dirty) await save(list);
    for (const file of files) {
      setUploading((n) => n + 1);
      try {
        const form = new FormData();
        form.append("file", file);
        const r = await api.post("/website/gallery", form, { headers: { "Content-Type": "multipart/form-data" } });
        onSaved(r.data);
        setList(r.data.gallery);
        toast.success(`Added ${file.name}`);
      } catch (e) {
        toast.error(formatApiErrorDetail(e?.response?.data?.detail) || `Couldn't upload ${file.name}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <label className="btn-ghost text-sm flex items-center gap-1 cursor-pointer" data-testid="upload-photo">
          <Upload size={14} /> {uploading ? `Uploading ${uploading}…` : "Add photos"}
          <input ref={fileRef} type="file" accept="image/*" multiple hidden disabled={!!uploading}
            onChange={(e) => e.target.files.length && upload([...e.target.files])} />
        </label>
        <SaveBar dirty={dirty} saving={saving} onSave={() => save(list)} testid="save-gallery" />
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        New photos are added at the end and go live straight away. Use the arrows to reorder, then save.
      </p>
      <div className="surface">
        {list.map((p, i) => (
          <div key={p.src} className="px-4 sm:px-6 py-4 flex gap-3 items-start" style={{ borderTop: i ? "1px solid var(--border)" : "none" }} data-testid={`photo-${i}`}>
            <img src={`${SITE}/${p.src_sm}`} alt="" className="shrink-0 rounded" style={{ width: 72, height: 90, objectFit: "cover" }} />
            <div className="flex-1 min-w-0 space-y-2">
              <RowControls i={i} count={list.length} testid="photo" onMove={(a, d) => update(move(list, a, d))}
                onRemove={(a) => window.confirm("Remove this photo from the website?") && update(list.filter((_, j) => j !== a))} />
              <Field label="Hidden description" hint={PHOTO_DESC_HINT}>
                <input className={inputCls} value={p.alt || ""} placeholder="e.g. Lakshmi in a red and black costume, arms raised"
                  onChange={(e) => update(list.map((x, j) => (j === i ? { ...x, alt: e.target.value } : x)))} />
              </Field>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const fmtDay = (iso) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");
const ytId = (v) => {
  const m = (v || "").match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([A-Za-z0-9_-]{11})|^([A-Za-z0-9_-]{11})$/);
  return m && (m[1] || m[2]);
};

// One past event: details, photos, videos, publish switch. A new entry must be
// saved once before photos can be uploaded (uploads attach to a saved entry).
function ArchiveEditor({ entry, onDone, onChanged }) {
  const [e, setE] = useState(() => ({
    ...entry,
    videos: (entry.videos || []).map((v) => ({ video: ytLink(v.video_id), title: v.title })),
    instagram: entry.instagram || [],
    photos: entry.photos || [],
  }));
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(0);
  const set = (k, v) => setE((x) => ({ ...x, [k]: v }));

  const payload = () => ({
    title: e.title, date: e.date, end_date: e.end_date || null, city: e.city, venue: e.venue,
    description: e.description, published: !!e.published, videos: e.videos, instagram: e.instagram, photos: e.photos,
    source_type: e.source_type || null, source_id: e.source_id || null,
  });

  const save = async () => {
    setSaving(true);
    try {
      const r = e.id ? await api.put(`/website/archive/${e.id}`, payload()) : await api.post("/website/archive", payload());
      toast.success(e.published ? "Saved — live on the website" : "Saved (not shown on the website yet)");
      onChanged();
      if (e.id) onDone(); else setE((x) => ({ ...x, id: r.data.id }));
    } catch (err) {
      toast.error(formatApiErrorDetail(err?.response?.data?.detail) || "Couldn't save");
    } finally {
      setSaving(false);
    }
  };

  const upload = async (files) => {
    for (const file of files) {
      setUploading((n) => n + 1);
      try {
        const form = new FormData();
        form.append("file", file);
        const r = await api.post(`/website/archive/${e.id}/photos`, form, { headers: { "Content-Type": "multipart/form-data" } });
        setE((x) => ({ ...x, photos: r.data.photos }));
        onChanged();
      } catch (err) {
        toast.error(formatApiErrorDetail(err?.response?.data?.detail) || `Couldn't upload ${file.name}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete "${e.title}" and its photos?`)) return;
    try {
      await api.delete(`/website/archive/${e.id}`);
      toast.success("Deleted");
      onChanged();
      onDone();
    } catch (err) {
      toast.error(formatApiErrorDetail(err?.response?.data?.detail) || "Couldn't delete");
    }
  };

  return (
    <div className="px-6 py-5 space-y-3" data-testid="archive-editor">
      <Field label="Title"><input className={inputCls} value={e.title || ""} placeholder="e.g. Rāvaṇa — Nehru Centre, London" onChange={(x) => set("title", x.target.value)} /></Field>
      <div className="flex gap-2 flex-wrap">
        <label className="text-xs" style={{ color: "var(--text-muted)" }}>Date
          <input type="date" className={inputCls} value={e.date || ""} onChange={(x) => set("date", x.target.value)} /></label>
        <label className="text-xs" style={{ color: "var(--text-muted)" }}>End date (optional)
          <input type="date" className={inputCls} value={e.end_date || ""} onChange={(x) => set("end_date", x.target.value)} /></label>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Venue"><input className={inputCls} value={e.venue || ""} onChange={(x) => set("venue", x.target.value)} /></Field>
        <Field label="City"><input className={inputCls} value={e.city || ""} onChange={(x) => set("city", x.target.value)} /></Field>
      </div>
      <Field label="About the event" hint="A few lines for the website — what was performed, who you danced with, how it went.">
        <textarea className={inputCls} rows={4} value={e.description || ""} onChange={(x) => set("description", x.target.value)} />
      </Field>

      <div className="uppercase-label pt-2">Videos</div>
      {e.videos.map((v, i) => (
        <div key={i} className="space-y-3 rounded p-3" style={{ border: "1px solid var(--border)" }}>
          <div className="flex justify-between items-center gap-3">
            <div className="shrink-0 rounded overflow-hidden" style={{ width: 96, height: 54, background: "#000" }}>
              {ytId(v.video) && <img src={`https://i.ytimg.com/vi/${ytId(v.video)}/mqdefault.jpg`} alt="" style={{ width: 96, height: 54, objectFit: "cover" }} />}
            </div>
            <RowControls i={i} count={e.videos.length} testid="archive-video" onMove={(a, d) => set("videos", move(e.videos, a, d))}
              onRemove={(a) => set("videos", e.videos.filter((_, j) => j !== a))} />
          </div>
          <Field label="YouTube link" hint={LINK_HINT}>
            <input className={inputCls} value={v.video} placeholder="https://youtu.be/…" onChange={(x) => set("videos", e.videos.map((y, j) => (j === i ? { ...y, video: x.target.value } : y)))} />
          </Field>
          <Field label="Title" hint="Shown under the video on the website.">
            <input className={inputCls} value={v.title} onChange={(x) => set("videos", e.videos.map((y, j) => (j === i ? { ...y, title: x.target.value } : y)))} />
          </Field>
        </div>
      ))}
      <button type="button" className="btn-ghost text-xs flex items-center gap-1" onClick={() => set("videos", [...e.videos, { video: "", title: "" }])}>
        <Plus size={12} /> Add video
      </button>

      <div className="uppercase-label pt-2">Instagram posts</div>
      {e.instagram.map((u, i) => (
        <div key={i} className="space-y-2 rounded p-3" style={{ border: "1px solid var(--border)" }}>
          <div className="flex justify-end">
            <RowControls i={i} count={e.instagram.length} testid="archive-insta" onMove={(a, d) => set("instagram", move(e.instagram, a, d))}
              onRemove={(a) => set("instagram", e.instagram.filter((_, j) => j !== a))} />
          </div>
          <Field label="Instagram link" hint="In Instagram, tap ⋯ or the share arrow → Copy link, then paste it here. Posts and reels both work; it must be a public post.">
            <input className={inputCls} value={u} placeholder="https://www.instagram.com/p/…"
              onChange={(x) => set("instagram", e.instagram.map((y, j) => (j === i ? x.target.value : y)))} />
          </Field>
        </div>
      ))}
      <button type="button" className="btn-ghost text-xs flex items-center gap-1" onClick={() => set("instagram", [...e.instagram, ""])}>
        <Plus size={12} /> Add Instagram post
      </button>

      <div className="uppercase-label pt-2">Photos</div>
      {!e.id ? (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>Save this entry once, then you can add photos.</div>
      ) : (
        <>
          {e.photos.map((p, i) => (
            <div key={p.src} className="flex gap-3 items-start rounded p-3" style={{ border: "1px solid var(--border)" }}>
              <img src={`${SITE}/${p.src_sm}`} alt="" className="shrink-0 rounded" style={{ width: 64, height: 80, objectFit: "cover" }} />
              <div className="flex-1 min-w-0 space-y-2">
                <RowControls i={i} count={e.photos.length} testid="archive-photo" onMove={(a, d) => set("photos", move(e.photos, a, d))}
                  onRemove={(a) => set("photos", e.photos.filter((_, j) => j !== a))} />
                <Field label="Hidden description" hint={PHOTO_DESC_HINT}>
                  <input className={inputCls} value={p.alt || ""}
                    onChange={(x) => set("photos", e.photos.map((y, j) => (j === i ? { ...y, alt: x.target.value } : y)))} />
                </Field>
              </div>
            </div>
          ))}
          <label className="btn-ghost text-xs flex items-center gap-1 cursor-pointer w-fit" data-testid="archive-upload">
            <Upload size={12} /> {uploading ? `Uploading ${uploading}…` : "Add photos"}
            <input type="file" accept="image/*" multiple hidden disabled={!!uploading}
              onChange={(x) => { const f = [...x.target.files]; x.target.value = ""; f.length && upload(f); }} />
          </label>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>New photos are saved straight away; reordering and removals need Save.</div>
        </>
      )}

      <label className="flex items-center gap-2 text-sm pt-2 cursor-pointer" data-testid="archive-published">
        <input type="checkbox" checked={!!e.published} onChange={(x) => set("published", x.target.checked)} />
        Show on the website
      </label>
      <div className="flex gap-2 flex-wrap pt-1">
        <button type="button" className="btn-pill" onClick={save} disabled={saving || !e.title || !e.date} data-testid="archive-save">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>Close</button>
        {e.id && <button type="button" className="btn-ghost ml-auto" style={{ color: "var(--error)" }} onClick={remove}>Delete entry</button>}
      </div>
    </div>
  );
}

function PastEventsTab() {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null); // entry object (new entries have no id)
  const load = () => api.get("/website/archive").then((r) => setData(r.data)).catch(() => setData(false));
  useEffect(() => { load(); }, []);

  if (data === null) return <div className="uppercase-label">Loading…</div>;
  if (data === false) return <div className="uppercase-label">Couldn't load past events.</div>;

  if (editing) {
    return (
      <div className="surface">
        <ArchiveEditor entry={editing} onChanged={load} onDone={() => { setEditing(null); load(); }} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <section>
        <div className="flex justify-between items-center mb-3 flex-wrap gap-2">
          <div className="uppercase-label">On the website ({data.entries.length})</div>
          <div className="flex gap-3 items-center">
            <a href={`${SITE}/past-events`} target="_blank" rel="noopener noreferrer" className="btn-ghost text-xs flex items-center gap-1">
              <ExternalLink size={12} /> View page
            </a>
            <button type="button" className="btn-ghost text-sm flex items-center gap-1" data-testid="archive-new"
              onClick={() => setEditing({ title: "", date: "", published: false, videos: [], instagram: [], photos: [] })}>
              <Plus size={14} /> New entry
            </button>
          </div>
        </div>
        <div className="surface">
          {data.entries.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
              No past events yet. Add one from "Recently finished" below, or start a new entry.
            </div>
          )}
          {data.entries.map((en, i) => (
            <button key={en.id} type="button" onClick={() => setEditing(en)} data-testid={`archive-entry-${i}`}
              className="w-full text-left px-6 py-3 flex justify-between items-center gap-4 text-sm"
              style={{ borderTop: i ? "1px solid var(--border)" : "none" }}>
              <div className="min-w-0">
                <div className="font-serif-display text-lg truncate">{en.title}</div>
                <div style={{ color: "var(--text-muted)" }}>
                  {fmtDay(en.date)}{en.city ? ` · ${en.city}` : ""} · {en.photos.length} photos · {en.videos.length} videos{(en.instagram || []).length ? ` · ${en.instagram.length} Instagram` : ""}
                </div>
              </div>
              <span className="uppercase-label shrink-0" style={{ color: en.published ? "var(--success)" : "var(--text-muted)" }}>
                {en.published ? "Live" : "Hidden"}
              </span>
            </button>
          ))}
        </div>
      </section>

      {data.suggestions.length > 0 && (
        <section>
          <div className="uppercase-label mb-3">Recently finished — not on the website yet</div>
          <div className="surface">
            {data.suggestions.map((sg, i) => (
              <div key={`${sg.source_type}-${sg.source_id}`} className="px-6 py-3 flex justify-between items-center gap-4 text-sm"
                style={{ borderTop: i ? "1px solid var(--border)" : "none" }}>
                <div className="min-w-0">
                  <div className="truncate">{sg.venue || sg.title}</div>
                  <div style={{ color: "var(--text-muted)" }}>
                    {fmtDay(sg.date)}{sg.city ? ` · ${sg.city}` : ""} · {sg.source_type === "event" ? "Workshop" : sg.title}
                  </div>
                </div>
                <button type="button" className="btn-ghost text-xs flex items-center gap-1 shrink-0" data-testid={`archive-suggest-${i}`}
                  onClick={() => setEditing({
                    title: sg.venue ? `${sg.title} — ${sg.venue}` : sg.title, date: sg.date, end_date: sg.end_date,
                    city: sg.city, venue: sg.venue, published: false, videos: [], instagram: sg.instagram ? [sg.instagram] : [], photos: [],
                    source_type: sg.source_type, source_id: sg.source_id,
                  })}>
                  <Plus size={12} /> Add to past events
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

const TABS = [
  { key: "productions", label: "Productions" },
  { key: "videos", label: "Videos" },
  { key: "gallery", label: "Gallery" },
  { key: "past", label: "Past events" },
];

export default function WebsitePage() {
  const [content, setContent] = useState(null);
  const [tab, setTab] = useState("productions");

  useEffect(() => {
    api.get("/website/content").then((r) => setContent(r.data)).catch(() => setContent(false));
  }, []);

  return (
    <div data-testid="website-page" className="space-y-6">
      <header className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="uppercase-label mb-2">www.pravaahacfm.com</div>
          <h1 className="font-serif-display text-4xl sm:text-5xl">Website</h1>
        </div>
        <a href={SITE} target="_blank" rel="noopener noreferrer" className="btn-ghost text-xs flex items-center gap-1">
          <ExternalLink size={13} /> View website
        </a>
      </header>

      <div className="flex gap-2 flex-wrap">
        {TABS.map((t) => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)} data-testid={`website-tab-${t.key}`}
            className="px-4 py-2 rounded text-sm border"
            style={{ borderColor: tab === t.key ? "var(--primary)" : "var(--border)", color: tab === t.key ? "var(--primary)" : "var(--text)" }}>
            {t.label}
          </button>
        ))}
      </div>

      {content === null && <div className="uppercase-label">Loading…</div>}
      {content === false && <div className="uppercase-label">Couldn't load the website content.</div>}
      {content && tab === "productions" && <ProductionsTab initial={content.productions} onSaved={setContent} />}
      {content && tab === "videos" && <VideosTab initial={content.videos} onSaved={setContent} />}
      {content && tab === "gallery" && <GalleryTab initial={content.gallery} onSaved={setContent} />}
      {tab === "past" && <PastEventsTab />}
    </div>
  );
}
