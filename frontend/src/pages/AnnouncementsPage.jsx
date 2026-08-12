import React, { useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import { Send, Upload, Loader2, Pencil, Trash2, Undo2, X, Users } from "lucide-react";
import { toast } from "sonner";

const fmtWhen = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
};

function Composer({ onPosted }) {
  const [body, setBody] = useState("");
  const [imagePath, setImagePath] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [posting, setPosting] = useState(false);
  const fileRef = useRef(null);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/uploads/photo", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setImagePath(data.path);
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const post = async (e) => {
    e.preventDefault();
    if (!body.trim()) return;
    setPosting(true);
    try {
      await api.post("/announcements", { body: body.trim(), image_path: imagePath });
      toast.success("Posted — students have been notified");
      setBody("");
      setImagePath(null);
      onPosted();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't post");
    } finally {
      setPosting(false);
    }
  };

  return (
    <form onSubmit={post} data-testid="announcement-composer" className="surface p-6 space-y-3">
      <h2 className="font-serif-display text-2xl">Post an update</h2>
      <textarea required rows={3} value={body} onChange={(e) => setBody(e.target.value)}
        placeholder="What do you want everyone to know?"
        data-testid="announcement-body-input"
        className="w-full bg-transparent border border-white/10 rounded px-3 py-2" />
      {imagePath && (
        <div className="text-xs flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
          Image attached
          <button type="button" onClick={() => setImagePath(null)} data-testid="announcement-image-remove">
            <X size={12} />
          </button>
        </div>
      )}
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
          className="btn-ghost flex items-center gap-2 text-xs" data-testid="announcement-image-btn">
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} {imagePath ? "Change image" : "Add image (optional)"}
        </button>
        <input ref={fileRef} type="file" accept="image/*" onChange={handleUpload} className="hidden" data-testid="announcement-image-input" />
        <button type="submit" disabled={posting || !body.trim()} className="btn-pill flex items-center gap-2" data-testid="announcement-post-btn">
          {posting && <Loader2 size={14} className="animate-spin" />} <Send size={14} /> Post to all students
        </button>
      </div>
    </form>
  );
}

function EditForm({ item, onClose, onSaved }) {
  const [body, setBody] = useState(item.body);
  const [saving, setSaving] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch(`/announcements/${item.id}`, { body });
      toast.success("Updated");
      onSaved();
      onClose();
    } catch (e2) {
      toast.error(formatApiErrorDetail(e2?.response?.data?.detail) || "Couldn't save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={save} className="mt-3 space-y-2" data-testid={`announcement-edit-form-${item.id}`}>
      <textarea required rows={3} value={body} onChange={(e) => setBody(e.target.value)}
        data-testid={`announcement-edit-input-${item.id}`}
        className="w-full bg-transparent border border-white/10 rounded px-3 py-2 text-sm" />
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-ghost text-xs" data-testid={`announcement-edit-cancel-${item.id}`}>Cancel</button>
        <button type="submit" disabled={saving} className="btn-pill text-xs" data-testid={`announcement-edit-save-${item.id}`}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

export default function AnnouncementsPage() {
  const [items, setItems] = useState(null);
  const [editingId, setEditingId] = useState(null);

  const load = () => {
    api.get("/announcements").then((r) => setItems(r.data)).catch(() => setItems([]));
  };

  useEffect(() => { load(); }, []);

  const retract = async (id) => {
    if (!window.confirm("Retract this update? Students will no longer see it.")) return;
    await api.post(`/announcements/${id}/retract`);
    toast.success("Retracted");
    load();
  };

  const unretract = async (id) => {
    await api.post(`/announcements/${id}/unretract`);
    toast.success("Restored");
    load();
  };

  const remove = async (id) => {
    if (!window.confirm("Permanently delete this update?")) return;
    await api.delete(`/announcements/${id}`);
    toast.success("Deleted");
    load();
  };

  if (items === null) return <div data-testid="announcements-loading" className="uppercase-label">Loading…</div>;

  return (
    <div data-testid="announcements-page" className="space-y-8">
      <header>
        <div className="uppercase-label mb-2">Studio</div>
        <h1 className="font-serif-display text-4xl sm:text-5xl">Announcements</h1>
      </header>

      <Composer onPosted={load} />

      {items.length === 0 ? (
        <div className="surface p-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>
          No updates posted yet.
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((a) => (
            <div key={a.id} data-testid={`announcement-row-${a.id}`}
              className="surface p-6" style={{ opacity: a.is_retracted ? 0.55 : 1 }}>
              <div className="flex items-start justify-between gap-3">
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>{fmtWhen(a.created_at)}</div>
                <div className="flex items-center gap-1 text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
                  <Users size={12} /> {a.read_count}/{a.total_students} read
                </div>
              </div>
              {a.is_retracted && (
                <div className="text-[10px] uppercase tracking-widest mt-1" style={{ color: "var(--error)" }}>Retracted</div>
              )}
              {editingId === a.id ? (
                <EditForm item={a} onClose={() => setEditingId(null)} onSaved={load} />
              ) : (
                <>
                  <p className="text-sm mt-2 whitespace-pre-wrap" style={{ textDecoration: a.is_retracted ? "line-through" : "none" }}>{a.body}</p>
                  {a.image_path && (
                    <AuthImage path={a.image_path} className="mt-3 rounded-lg max-h-64 object-cover" />
                  )}
                </>
              )}
              {editingId !== a.id && (
                <div className="flex items-center gap-3 mt-4">
                  <button type="button" onClick={() => setEditingId(a.id)} className="btn-ghost text-xs flex items-center gap-1" data-testid={`announcement-edit-btn-${a.id}`}>
                    <Pencil size={12} /> Edit
                  </button>
                  {a.is_retracted ? (
                    <button type="button" onClick={() => unretract(a.id)} className="btn-ghost text-xs flex items-center gap-1" data-testid={`announcement-unretract-btn-${a.id}`}>
                      <Undo2 size={12} /> Restore
                    </button>
                  ) : (
                    <button type="button" onClick={() => retract(a.id)} className="btn-ghost text-xs flex items-center gap-1" data-testid={`announcement-retract-btn-${a.id}`}>
                      <Undo2 size={12} /> Retract
                    </button>
                  )}
                  <button type="button" onClick={() => remove(a.id)} className="btn-ghost text-xs flex items-center gap-1" style={{ color: "var(--error)" }} data-testid={`announcement-delete-btn-${a.id}`}>
                    <Trash2 size={12} /> Delete
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
